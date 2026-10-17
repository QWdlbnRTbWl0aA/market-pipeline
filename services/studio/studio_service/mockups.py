"""Reusable procedural photo-style scenes; product pixels are only composited.

No network, AI painting, source writes or random runtime variation. Perspective,
shadow and framing operate on an alpha surface so stacks survive every view.
"""
from functools import lru_cache
import hashlib
import math
import random
import re
from .storage import Invalid

SIZE=(1200,1400)
VERSION='studio-scenes-v2'


@lru_cache(maxsize=8)
def backdrop(kind,color):
    from PIL import Image,ImageDraw,ImageFilter,ImageColor
    rgb=ImageColor.getrgb(color);small=Image.new('RGB',(120,140));pixels=[]
    for y in range(140):
        for x in range(120):
            light=9-15*(x/120+y/140)/2+6*math.exp(-((x-20)**2+(y-15)**2)/4000)
            pixels.append(tuple(max(0,min(255,round(c+light))) for c in rgb))
    small.putdata(pixels);canvas=small.resize(SIZE,Image.Resampling.BICUBIC)
    rng=random.Random(271828);grain=Image.new('RGB',SIZE)
    tile=Image.new('RGB',(128,128));tile.putdata([(v,v,v) for v in (rng.randrange(80,180) for _ in range(128*128))])
    for y in range(0,SIZE[1],128):
        for x in range(0,SIZE[0],128):grain.paste(tile,(x,y))
    canvas=Image.blend(canvas,grain,.025);layer=Image.new('RGBA',SIZE);draw=ImageDraw.Draw(layer)
    if kind=='frame':
        # Warm plaster wall with a shallow ledge and softly lit plant.
        draw.rectangle((0,1255,1200,1278),fill=(109,85,63,100));draw.rectangle((0,1248,1200,1256),fill=(255,251,240,255))
        draw.rectangle((0,1278,1200,1400),fill=(211,197,175,110))

    else:
        # Pale oak grain and a folded linen corner give paper a physical setting.
        for y in range(-20,1420,5):
            points=[(x,y+round(4*math.sin(x/230+y/90))) for x in range(0,1201,30)]
            draw.line(points,fill=(126,102,76,rng.randrange(4,17)),width=1)
        draw.polygon([(-20,-20),(330,-20),(245,320),(30,410)],fill=(237,231,216,250))
        for y in range(5,400,9):draw.line((0,y,285,y-70),fill=(163,151,131,22),width=1)
        # Drawing tools are scene props, kept towards the edges behind the pages.
        for i,c in enumerate(((103,145,145),(198,151,83),(114,134,164))):
            x=1080+i*25;draw.line((x,980,x-40,1220),fill=(*tuple(max(0,v-20) for v in c),255),width=13)
            draw.line((x-2,980,x-42,1220),fill=(*c,255),width=8)
            draw.line((x-4,980,x-44,1220),fill=(*tuple(min(255,v+35) for v in c),255),width=2)
            draw.ellipse((x-6,974,x+6,985),fill=(*c,255))
            draw.polygon([(x-46,1220),(x-34,1223),(x-43,1252)],fill=(199,165,115,255))
            draw.line((x-42,1246,x-43,1252),fill=(58,62,60,255),width=3)
    canvas=Image.alpha_composite(canvas.convert('RGBA'),layer).convert('RGB')
    light=Image.new('RGBA',SIZE);ld=ImageDraw.Draw(light)
    for offset in (0,110,220):ld.polygon([(760+offset,-50),(850+offset,-50),(1110+offset,610),(1020+offset,610)],fill=(95,79,62,12))
    light=light.filter(ImageFilter.GaussianBlur(18));return Image.alpha_composite(canvas.convert('RGBA'),light).convert('RGB')


def quad_for(x,y,w,h,perspective):
    if perspective=='left':return [(x+w*.09,y+h*.05),(x+w,y),(x+w,y+h),(x,y+h*.95)]
    if perspective=='right':return [(x,y),(x+w*.91,y+h*.05),(x+w,y+h*.95),(x,y+h)]
    return [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]


def composite(canvas,surface,quad):
    from PIL import Image,ImageFilter
    from .production import perspective_coefficients
    coeff=perspective_coefficients(quad,[(0,0),(surface.width,0),(surface.width,surface.height),(0,surface.height)])
    warped=surface.convert('RGBA').transform(SIZE,Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    mask=warped.getchannel('A')
    # Soft ambient shadow plus a narrow contact shadow; use the real alpha mask.
    for distance,blur,opacity in ((19,23,52),(5,5,65)):
        shifted=Image.new('L',SIZE);shifted.paste(mask,(distance//2,distance));shifted=shifted.filter(ImageFilter.GaussianBlur(blur)).point(lambda a:round(a*opacity/255))
        shadow=Image.new('RGBA',SIZE,(53,43,32,0));shadow.putalpha(shifted);canvas.alpha_composite(shadow)
    canvas.alpha_composite(warped)


def framed(image):
    from PIL import Image,ImageDraw
    mat=24;border=25;padding=mat+border;surface=Image.new('RGBA',(image.width+2*padding,image.height+2*padding),'#b39a75');draw=ImageDraw.Draw(surface)
    # Four wood tones, an outer highlight and inner bevel around a cream mat.
    draw.polygon([(0,0),(surface.width,0),(surface.width-border,border),(border,border)],fill='#cab18c')
    draw.polygon([(0,0),(border,border),(border,surface.height-border),(0,surface.height)],fill='#aa8963')
    draw.polygon([(0,surface.height),(border,surface.height-border),(surface.width-border,surface.height-border),(surface.width,surface.height)],fill='#8e7152')
    draw.rectangle((border,border,surface.width-border-1,surface.height-border-1),fill='#faf7f0',outline='#5a4b3a',width=2)
    for inset,color in ((0,'#bdb5a6'),(1,'#e9e4db')):draw.rectangle((padding-inset-1,padding-inset-1,padding+image.width+inset,padding+image.height+inset),outline=color)
    surface.paste(image,(padding,padding));return surface


def stacked(image,pages):
    from PIL import Image,ImageFilter
    pad=28;surface=Image.new('RGBA',(image.width+2*pad,image.height+2*pad))
    for index,(angle,offset) in enumerate(((-3,10),(2,5),(0,0))):
        sheet=(pages[index%len(pages)] if pages and index<2 else image).copy().convert('RGBA');sheet=sheet.resize(image.size,Image.Resampling.LANCZOS)
        paper=Image.new('RGBA',surface.size);paper.paste(sheet,(pad+offset,pad+offset));paper=paper.rotate(angle,resample=Image.Resampling.BICUBIC)
        shadow=Image.new('RGBA',surface.size,(40,34,27,0));shadow.putalpha(paper.getchannel('A').filter(ImageFilter.GaussianBlur(3)).point(lambda a:round(a*.15)))
        surface.alpha_composite(shadow);surface.alpha_composite(paper)
    return surface


def arranged(pages,width,height):
    from PIL import Image,ImageFilter
    columns=min(3,len(pages));rows=math.ceil(len(pages)/columns);gap=18;cellw=(width-gap*(columns-1))/columns;cellh=(height-gap*(rows-1))/rows
    surface=Image.new('RGBA',(width,height))
    for index,page in enumerate(pages):
        image=page.copy().convert('RGBA');image.thumbnail((round(cellw-16),round(cellh-16)),Image.Resampling.LANCZOS)
        row=index//columns;count=min(columns,len(pages)-row*columns);start=(width-(count*cellw+(count-1)*gap))/2
        x=round(start+(index%columns)*(cellw+gap)+(cellw-image.width)/2);y=round(row*(cellh+gap)+(cellh-image.height)/2)
        card=Image.new('RGBA',surface.size);card.paste(image,(x,y));shadow=Image.new('RGBA',surface.size,(40,34,27,0))
        alpha=Image.new('L',surface.size);alpha.paste(image.getchannel('A'),(x+4,y+7));shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(6)).point(lambda a:round(a*.22)))
        surface.alpha_composite(shadow);surface.alpha_composite(card)
    return surface


def render(page,template,pages=None):
    from PIL import Image
    from .production import png
    if not isinstance(template,dict) or set(template)-{'kind','scale','x','y','background','perspective','crop'}:raise Invalid('Unknown mockup settings')
    kind=template.get('kind','frame');scale=template.get('scale',.82);dx=template.get('x',0);dy=template.get('y',0)
    if kind not in ('frame','flat','stack','bundle') or type(scale) not in (int,float) or not math.isfinite(scale) or not .3<=scale<=1:raise Invalid('Invalid mockup placement')
    if any(type(v) not in (int,float) or not math.isfinite(v) or not -.15<=v<=.15 for v in (dx,dy)):raise Invalid('Invalid mockup offset')
    color=template.get('background','#eee8df');view=template.get('perspective','straight');crop=template.get('crop',[0,0,1,1])
    if not isinstance(color,str) or not re.fullmatch('#[0-9a-fA-F]{6}',color) or view not in ('straight','left','right'):raise Invalid('Invalid mockup appearance')
    if not isinstance(crop,list) or len(crop)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in crop) or crop[2]<=crop[0] or crop[3]<=crop[1]:raise Invalid('Invalid crop')
    source_hash=hashlib.sha256(png(page)).hexdigest()
    def cropped(image):
        result=image.crop((round(crop[0]*image.width),round(crop[1]*image.height),round(crop[2]*image.width),round(crop[3]*image.height)))
        if min(result.size)<1:raise Invalid('Empty mockup crop')
        return result
    image=cropped(page);supplied=[cropped(p) for p in pages] if pages else []
    image.thumbnail((round(900*scale),round(1150*scale)),Image.Resampling.LANCZOS)
    if kind=='bundle' and supplied:surface=arranged(supplied,round(1020*scale),round(1160*scale))
    elif kind=='frame':surface=framed(image)
    elif kind=='stack':surface=stacked(image,supplied)
    else:surface=image.convert('RGBA')
    x=round((1200-surface.width)/2+dx*1200);y=round((1400-surface.height)/2+dy*1400)
    if x<12 or y<12 or x+surface.width>1188 or y+surface.height>1388:raise Invalid('Mockup placement clips the product; reduce its size or position offset')
    quad=quad_for(x,y,surface.width,surface.height,view);canvas=backdrop('frame' if kind=='frame' else 'desk',color).copy().convert('RGBA');composite(canvas,surface,quad)
    return canvas.convert('RGB'),{'box':[x,y,surface.width,surface.height],'perspective_quad':quad,'crop':crop,'source_image_sha256':source_hash,
        'source_page_hashes':[hashlib.sha256(png(p)).hexdigest() for p in (pages or [page])],
        'renderer_version':VERSION,'scene':'warm-wall' if kind=='frame' else 'oak-worktable','displayed_pages':len(supplied) if kind=='bundle' and supplied else 3 if kind=='stack' else 1,
        'compositing':'Saved artwork composited onto reusable scene; deterministic resize/crop/perspective, physical mat/stack, alpha shadows. No generative repainting.'}
