"""Deterministic print composition, exact-artwork mockups and listing contracts."""
import base64
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import zipfile
from .storage import Invalid, canonical, digest, write, write_bytes

PAPERS={'A4':(210,297),'Letter':(215.9,279.4)}


def plan(document, brief):
    definition=document.get('definition') or {};units=[]
    for component in definition.get('components',[]):
        content=component.get('content',[])
        if component.get('quantity')!=len(content):raise Invalid('Brief inventory/count mismatch')
        for text in content:
            name=component['name'];kind='text' if re.search(r'guide|instruction|הדרכ|הוראות',name,re.I) else 'illustration'
            units.append({'id':f'unit-{len(units)+1:02d}','title':name[:120], 'description':text,'kind':kind,
                          'visible_text':text if kind=='text' else ''})
    if not units:
        for value in brief.get('deliverables',[]):
            units.append({'id':f'unit-{len(units)+1:02d}','title':value[:120],'description':value,'kind':'illustration','visible_text':''})
    if not units:units=[{'id':'unit-01','title':brief.get('concept','')[:120] or 'Original printable','description':brief.get('concept') or 'An original printable illustration','kind':'illustration','visible_text':''}]
    value={'version':1,'family':'','units':units,'representative_id':next((u['id'] for u in units if u['kind']=='illustration'),units[0]['id']),
           'style':brief.get('visual_direction') or 'Proposed starting direction: clear original illustration, white background and generous spacing',
           'constraints':brief.get('requirements',''),
           'assumptions':['Each listed content unit is a separate page; review/edit the inventory before production.',
                          'A4 and US Letter, 300 DPI, 10 mm safe margins; no bleed unless selected.',
                          'Style and unspecified details are editable design assumptions, not observed market facts.']}
    return checked_plan(value)


def checked_plan(value):
    if not isinstance(value,dict) or set(value)!={'version','family','units','representative_id','style','constraints','assumptions'}:raise Invalid('Complete production inventory required')
    if type(value['version']) is not int or value['version']<1 or not isinstance(value['family'],str) or len(value['family'])>120:raise Invalid('Invalid inventory metadata')
    if not isinstance(value['style'],str) or len(value['style'])>8000:raise Invalid('Bounded style required')
    if not isinstance(value['constraints'],str) or len(value['constraints'])>8000:raise Invalid('Bounded source requirements required')
    units=value['units']
    if not isinstance(units,list) or not 1<=len(units)<=30:raise Invalid('One to thirty content units supported')
    ids=set()
    for unit in units:
        if not isinstance(unit,dict) or set(unit)!={'id','title','description','kind','visible_text'}:raise Invalid('Explicit content unit required')
        if not isinstance(unit['id'],str) or not re.fullmatch(r'unit-[0-9]{2}',unit['id']) or unit['id'] in ids:raise Invalid('Unique content unit identities required')
        ids.add(unit['id'])
        for key,limit in (('title',120),('description',4000),('visible_text',4000)):
            if not isinstance(unit[key],str) or len(unit[key])>limit:raise Invalid('Bounded unit text required')
        if not unit['description'].strip() or unit['kind'] not in ('illustration','text'):raise Invalid('Explicit unit contents/kind required')
    if value['representative_id'] not in ids:raise Invalid('Representative must be an inventory unit')
    if not isinstance(value['assumptions'],list) or len(value['assumptions'])>20 or any(not isinstance(x,str) or len(x)>1000 for x in value['assumptions']):raise Invalid('Bounded editable assumptions required')
    return value


def settings(value):
    if not isinstance(value,dict) or set(value)!={'formats','dpi','margin_mm','bleed_mm','color_mode'}:raise Invalid('Explicit print specification required')
    if not isinstance(value['formats'],list) or not 1<=len(value['formats'])<=2 or len(set(value['formats']))!=len(value['formats']) or any(f not in PAPERS for f in value['formats']):raise Invalid('A4/Letter formats required')
    if type(value['dpi']) is not int or not 150<=value['dpi']<=600:raise Invalid('Print DPI outside supported bounds')
    for key,lo,hi in (('margin_mm',5,30),('bleed_mm',0,10)):
        if type(value[key]) not in (int,float) or not math.isfinite(value[key]) or not lo<=value[key]<=hi:raise Invalid('Invalid print margins/bleed')
    if value['color_mode'] not in ('color','grayscale'):raise Invalid('Invalid print color mode')
    return value


def image_size(spec):
    spec=settings(spec)
    w=max(PAPERS[f][0]-2*spec['margin_mm'] for f in spec['formats'])
    h=max(PAPERS[f][1]-2*spec['margin_mm'] for f in spec['formats'])
    dimensions=[math.ceil(x*spec['dpi']/25.4/16)*16 for x in (w,h)]
    if max(dimensions)>3840 or dimensions[0]*dimensions[1]>8294400:raise Invalid('Native resolution exceeds this provider route; reduce DPI/print size before generation')
    # Small final requests still meet the provider minimum area.
    while dimensions[0]*dimensions[1]<655360:dimensions=[x+16 for x in dimensions]
    return dimensions


def preflight(inventory,spec):
    from PIL import features
    checked_plan(inventory);settings(spec);image_size(spec);font(round(12*spec['dpi']/72))
    if any(re.search(r'[\u0590-\u08ff]',u['visible_text']) for u in inventory['units']) and not features.check('raqm'):raise Invalid('RTL typography requires the Pillow RAQM runtime before production')


def raster(body):
    from PIL import Image
    if not isinstance(body,bytes) or len(body)>30_000_000:raise Invalid('Bounded raster bytes required')
    with Image.open(io.BytesIO(body)) as source:
        if source.format not in ('PNG','JPEG','WEBP') or source.width*source.height>40_000_000 or getattr(source,'n_frames',1)!=1:raise Invalid('Bounded still raster required')
        source.load();image=source.convert('RGBA');base=Image.new('RGB',image.size,'white');base.paste(image,mask=image.getchannel('A'));return base


def png(image,dpi=300):
    out=io.BytesIO();image.save(out,format='PNG',dpi=(dpi,dpi));return out.getvalue()


def font(size):
    from PIL import ImageFont
    try:return ImageFont.truetype('DejaVuSans.ttf',size)
    except OSError:raise Invalid('DejaVu Sans runtime font required for deterministic print text') from None


def text_lines(draw,text,typeface,width):
    from PIL import features
    rtl=bool(re.search(r'[\u0590-\u08ff]',text))
    if rtl and not features.check('raqm'):raise Invalid('RTL printing requires Pillow RAQM')
    direction='rtl' if rtl else 'ltr';lines=[]
    for paragraph in text.splitlines():
        line=''
        for word in paragraph.split():
            candidate=(line+' '+word).strip()
            if draw.textlength(candidate,font=typeface,direction=direction)>width:
                if not line:raise Invalid('Printed word exceeds text box width')
                lines.append(line);line=word
                if draw.textlength(word,font=typeface,direction=direction)>width:raise Invalid('Printed word exceeds text box width')
            else:line=candidate
        lines.append(line)
    return lines,direction


def pdf(pages):
    """Raster pages with exact physical Media/Trim/Bleed boxes; no font fallback."""
    objects=[b'',b''];kids=[]
    for image,trim,bleed in pages:
        out=io.BytesIO();image.save(out,format='JPEG',quality=98,subsampling=0)
        data=out.getvalue();image_id=len(objects)+1
        objects.append(f'<< /Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n'.encode()+data+b'\nendstream')
        w,h=[(x+2*bleed)*72/25.4 for x in trim];b=bleed*72/25.4
        content=f'q {w:.5f} 0 0 {h:.5f} 0 0 cm /Im0 Do Q'.encode();content_id=len(objects)+1
        objects.append(f'<< /Length {len(content)} >>\nstream\n'.encode()+content+b'\nendstream')
        page_id=len(objects)+1;kids.append(page_id)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.5f} {h:.5f}] /TrimBox [{b:.5f} {b:.5f} {w-b:.5f} {h-b:.5f}] /BleedBox [0 0 {w:.5f} {h:.5f}] /Resources << /XObject << /Im0 {image_id} 0 R >> >> /Contents {content_id} 0 R >>'.encode())
    objects[0]=b'<< /Type /Catalog /Pages 2 0 R >>';objects[1]=f'<< /Type /Pages /Count {len(kids)} /Kids [ {" ".join(str(k)+" 0 R" for k in kids)} ] >>'.encode()
    body=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n');offsets=[0]
    for i,value in enumerate(objects,1):offsets.append(len(body));body.extend(f'{i} 0 obj\n'.encode()+value+b'\nendobj\n')
    xref=len(body);body.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:body.extend(f'{offset:010d} 00000 n \n'.encode())
    body.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode());return bytes(body)


def assemble(directory,inventory,spec,assets,revision):
    from PIL import Image,ImageDraw,ImageOps
    checked_plan(inventory);settings(spec);directory=Path(directory);files=[];checks=[]
    def save(name,body,metadata=None):
        write_bytes(directory/name,body);files.append({'file':name,'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),**(metadata or {})})
    for paper in spec['formats']:
        pages=[];trim=PAPERS[paper];dpi=spec['dpi'];bleed=spec['bleed_mm'];margin=spec['margin_mm']
        width,height=[round((v+2*bleed)*dpi/25.4) for v in trim];pad=round((margin+bleed)*dpi/25.4)
        for unit in inventory['units']:
            image=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(image);source_svg=''
            if unit['kind']=='illustration':
                asset=assets[unit['id']];original=raster(asset['content']);box=(width-2*pad,height-2*pad)
                if unit['visible_text']:box=(box[0],box[1]-round(18*dpi/25.4))
                scale=min(box[0]/original.width,box[1]/original.height)
                effective=dpi/scale
                checks.append({'unit_id':unit['id'],'format':paper,'check':'native_artwork_dpi','value':round(effective,2),'required':dpi,'passed':effective+0.5>=dpi})
                if effective+0.5<dpi:raise Invalid('Artwork does not contain enough native detail for the requested print specification')
                rendered=original.resize((round(original.width*scale),round(original.height*scale)),Image.Resampling.LANCZOS)
                x=pad+(box[0]-rendered.width)//2;y=pad+(box[1]-rendered.height)//2;image.paste(rendered,(x,y))
                source_svg=f'<image x="{x}" y="{y}" width="{rendered.width}" height="{rendered.height}" href="data:image/png;base64,{base64.b64encode(png(original)).decode()}"/>'
                top=height-pad-round(14*dpi/25.4)
            else:top=pad
            visible=unit['visible_text'];font_size=round(12*dpi/72);typeface=font(font_size)
            if visible:
                lines,direction=text_lines(draw,visible,typeface,width-2*pad);line_height=round(font_size*1.5)
                if top+line_height*len(lines)>height-pad:raise Invalid('Print text clips the safe area; split or shorten the page')
                for line in lines:
                    x=width-pad if direction=='rtl' else pad
                    draw.text((x,top),line,font=typeface,fill='#202b28',direction=direction,anchor='ra' if direction=='rtl' else 'la')
                    source_svg+=f'<text x="{x}" y="{top+font_size}" font-family="DejaVu Sans" font-size="{font_size}" direction="{direction}" text-anchor="{"end" if direction=="rtl" else "start"}">{html.escape(line)}</text>'
                    top+=line_height
            if spec['color_mode']=='grayscale':image=ImageOps.grayscale(image).convert('RGB')
            prefix=f'{paper}/{unit["id"]}';save(prefix+'.png',png(image,dpi),{'unit_id':unit['id'],'width':width,'height':height,'dpi':dpi,'format':paper,'role':'print_page'})
            preview=image.copy();preview.thumbnail((480,680));out=io.BytesIO();preview.save(out,format='JPEG',quality=75)
            save(prefix+'.preview.jpg',out.getvalue(),{'unit_id':unit['id'],'format':paper,'role':'preview'})
            save(prefix+'.svg',(f'<svg xmlns="http://www.w3.org/2000/svg" width="{trim[0]+2*bleed}mm" height="{trim[1]+2*bleed}mm" viewBox="0 0 {width} {height}"><rect width="{width}" height="{height}" fill="white"/>'+source_svg+'</svg>').encode(),{'role':'editable_layout_source','unit_id':unit['id']})
            pages.append((image,trim,bleed));checks.append({'unit_id':unit['id'],'format':paper,'check':'safe_area_and_text_fit','passed':True})
        save(paper+'/bundle.pdf',pdf(pages),{'role':'print_pdf','pages':len(pages),'format':paper})
    manifest={'schema_version':1,'revision':revision,'inventory_sha256':digest(inventory),'settings':spec,'units':inventory['units'],'files':files,
              'checks':checks,'automatic_checks_passed':all(x['passed'] for x in checks),'human_approved':False,
              'quality_note':'Mechanical checks only. Human visual/content and physical print proof approval remains required.',
              'font':'DejaVu Sans; text is rasterized into print PDF/PNG, editable SVG uses this font family.'}
    manifest['id']=digest(manifest);write(directory/'manifest.json',manifest);return manifest


def compose_mockup(page,template):
    """Composite exact approved page pixels; never repaint artwork."""
    from PIL import Image,ImageDraw,ImageFilter
    if not isinstance(template,dict) or set(template)-{'kind','scale','x','y','background','perspective','crop'}:raise Invalid('Unknown mockup settings')
    kind=template.get('kind','frame');scale=template.get('scale',.82);dx=template.get('x',0);dy=template.get('y',0)
    if kind not in ('frame','flat','stack','bundle') or type(scale) not in (int,float) or not .3<=scale<=1:raise Invalid('Invalid mockup placement')
    if any(type(v) not in (int,float) or not -.15<=v<=.15 for v in (dx,dy)):raise Invalid('Invalid mockup offset')
    background=template.get('background','#eee8df');perspective=template.get('perspective','straight');crop=template.get('crop',[0,0,1,1])
    if not isinstance(background,str) or not re.fullmatch('#[0-9a-fA-F]{6}',background) or perspective not in ('straight','left','right'):raise Invalid('Invalid mockup appearance')
    if not isinstance(crop,list) or len(crop)!=4 or any(type(v) not in (int,float) or not 0<=v<=1 for v in crop) or crop[2]<=crop[0] or crop[3]<=crop[1]:raise Invalid('Invalid crop')
    source_hash=hashlib.sha256(png(page)).hexdigest()
    canvas=Image.new('RGB',(1200,1400),background);draw=ImageDraw.Draw(canvas)
    image=page.crop((round(crop[0]*page.width),round(crop[1]*page.height),round(crop[2]*page.width),round(crop[3]*page.height)))
    if min(image.size)<1:raise Invalid('Empty mockup crop')
    image.thumbnail((int(900*scale),int(1150*scale)))
    x=(1200-image.width)//2+round(dx*1200);y=(1400-image.height)//2+round(dy*1400)
    if x<25 or y<25 or x+image.width>1175 or y+image.height>1375:raise Invalid('Mockup placement clips the product')
    shadow=Image.new('RGBA',canvas.size);sd=ImageDraw.Draw(shadow);sd.rectangle((x+10,y+14,x+image.width+10,y+image.height+14),fill=(30,30,30,55));shadow=shadow.filter(ImageFilter.GaussianBlur(14));canvas.paste(shadow,(0,0),shadow)
    if kind=='stack':
        for shift in (18,10):draw.rectangle((x+shift,y+shift,x+image.width+shift,y+image.height+shift),fill='white',outline='#cabfb3',width=2)
    if kind=='frame':draw.rectangle((x-18,y-18,x+image.width+18,y+image.height+18),fill='#7c634b')
    quad=[(x,y),(x+image.width,y),(x+image.width,y+image.height),(x,y+image.height)]
    if perspective!='straight':
        inset=image.width*.12;vertical=image.height*.08
        quad=[(x+inset,y+vertical),(x+image.width,y),(x+image.width,y+image.height),(x,y+image.height-vertical)] if perspective=='left' else [(x,y),(x+image.width-inset,y+vertical),(x+image.width,y+image.height-vertical),(x,y+image.height)]
        canvas=Image.new('RGB',canvas.size,background)
        layer=Image.new('RGBA',canvas.size);ld=ImageDraw.Draw(layer);ld.polygon([(a+12,b+15) for a,b in quad],fill=(20,20,20,65));layer=layer.filter(ImageFilter.GaussianBlur(12));canvas.paste(layer,(0,0),layer)
        if kind=='frame':
            cx=sum(a for a,b in quad)/4;cy=sum(b for a,b in quad)/4
            ImageDraw.Draw(canvas).polygon([(cx+(a-cx)*1.06,cy+(b-cy)*1.06) for a,b in quad],fill='#7c634b')
        coefficients=perspective_coefficients(quad,[(0,0),(image.width,0),(image.width,image.height),(0,image.height)])
        warped=image.convert('RGBA').transform(canvas.size,Image.Transform.PERSPECTIVE,coefficients,Image.Resampling.BICUBIC)
        canvas.paste(warped,(0,0),warped)
    else:canvas.paste(image,(x,y))
    return canvas,{'box':[x,y,image.width,image.height],'perspective_quad':quad,'crop':crop,'source_image_sha256':source_hash,'compositing':'Exact source pixels with deterministic resize/crop/perspective and alpha mask; no generative repainting'}


def perspective_coefficients(destination,source):
    matrix=[]
    for (x,y),(u,v) in zip(destination,source):
        matrix.extend([[x,y,1,0,0,0,-u*x,-u*y,u],[0,0,0,x,y,1,-v*x,-v*y,v]])
    for col in range(8):
        pivot=max(range(col,8),key=lambda row:abs(matrix[row][col]));matrix[col],matrix[pivot]=matrix[pivot],matrix[col]
        divisor=matrix[col][col]
        if abs(divisor)<1e-10:raise Invalid('Degenerate mockup perspective')
        matrix[col]=[x/divisor for x in matrix[col]]
        for row in range(8):
            if row==col:continue
            factor=matrix[row][col];matrix[row]=[a-factor*b for a,b in zip(matrix[row],matrix[col])]
    return tuple(matrix[i][-1] for i in range(8))


def contact_sheet(pages):
    from PIL import Image
    columns=min(3,len(pages));rows=math.ceil(len(pages)/columns)
    result=Image.new('RGB',(columns*400,rows*560),'#f7f3eb')
    for index,page in enumerate(pages):
        image=page.copy();image.thumbnail((360,520));x=(index%columns)*400+(400-image.width)//2;y=(index//columns)*560+(560-image.height)//2
        result.paste(image,(x,y))
    return result


LISTING_SCHEMA={'type':'object','additionalProperties':False,'required':['titles','description','tags'],'properties':{
    'titles':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'string'}},'description':{'type':'string'},
    'tags':{'type':'array','minItems':13,'maxItems':13,'items':{'type':'string'}}}}


def checked_listing(value):
    if not isinstance(value,dict) or set(value)!=set(LISTING_SCHEMA['required']):raise Invalid('Complete listing copy required')
    if not isinstance(value['titles'],list) or len(value['titles'])!=2 or any(not isinstance(t,str) or not 1<=len(t)<=140 for t in value['titles']):raise Invalid('Two titles up to 140 characters required')
    if not isinstance(value['description'],str) or not 40<=len(value['description'])<=10000:raise Invalid('Bounded listing description required')
    if not isinstance(value['tags'],list) or len(value['tags'])!=13 or any(not isinstance(t,str) or not 1<=len(t)<=20 for t in value['tags']) or len({t.casefold().strip() for t in value['tags']})!=13:raise Invalid('Thirteen unique tags of up to twenty characters required')
    if re.search(r'guaranteed sales|proven demand|bestseller|best seller|search volume',canonical(value).decode(),re.I):raise Invalid('Unsupported market claims in listing copy')
    return value


def factual_listing(value,manifest):
    checked_listing(value);value={**value,'titles':list(value['titles']),'tags':list(value['tags'])}
    text=' '.join(value['titles'])+' '+value['description'].split('\n\nIncluded files (verified):\n')[0]
    counts={len(manifest['units']),sum(u['kind']=='illustration' for u in manifest['units'])}
    for match in re.finditer(r'\b(\d+)\s+(?:printable\s+)?(?:pages|prints|pictures|illustrations)\b',text,re.I):
        if int(match.group(1)) not in counts:raise Invalid('Listing quantity contradicts the finished inventory')
    formats=', '.join(f'{f} ({PAPERS[f][0]} × {PAPERS[f][1]} mm)' for f in manifest['settings']['formats'])
    facts='\n\nIncluded files (verified):\n'+str(len(manifest['units']))+' content pages per format: '+formats+'.\n'+str(manifest['settings']['dpi'])+' DPI PNG pages and one complete PDF per format. Digital download; no physical item. Print at actual size / 100%.'
    value['description']=value['description'].split('\n\nIncluded files (verified):\n')[0].rstrip()+facts
    return checked_listing(value)


def package(directory,manifest,copy_value,mockups):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
        for record in manifest['files']:
            path=directory/record['file'];body=path.read_bytes()
            if path.is_symlink() or hashlib.sha256(body).hexdigest()!=record['sha256']:raise Invalid('Product file changed after review')
            archive.writestr('customer/'+record['file'],body)
        archive.writestr('product-manifest.json',canonical(manifest));archive.writestr('listing.json',canonical(copy_value))
        for record in mockups:
            path=directory.parent.parent/record['file'];body=path.read_bytes()
            if path.is_symlink() or hashlib.sha256(body).hexdigest()!=record['sha256']:raise Invalid('Mockup changed after review')
            archive.writestr('listing-assets/'+Path(record['file']).name,body)
        archive.writestr('PRINTING.txt','Print at actual size / 100%. Check paper format and printer margins. Colours vary by printer. Product content and physical print proofs require human review.\n')
    return data.getvalue()


def customer_package(directory,manifest):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
        for record in manifest['files']:
            if record.get('role') not in ('print_page','print_pdf'):continue
            body=(directory/record['file']).read_bytes()
            if hashlib.sha256(body).hexdigest()!=record['sha256']:raise Invalid('Customer file checksum mismatch')
            archive.writestr(record['file'],body)
        archive.writestr('PRINTING.txt','Digital download. Print at actual size / 100%; choose the matching paper format. No physical product is included.\n')
    return data.getvalue()
