"""Mock generation, durable local notifications and blocked listing adapters."""
import html
from pathlib import Path
import re
from xml.etree import ElementTree
from .ports import Asset
from .storage import Conflict, Invalid, digest, read, write


class MockGenerator:
    def generate(self, request):
        count = request['count']; brief = request['brief']; professional = request['mode'] == 'professional'
        size = request.get('settings') or {}
        width, height = (size.get('pixel_width', 1200), size.get('pixel_height', 1600)) if professional else (320, 420)
        palettes = [('f2eee5', '245c52'), ('eee8f3', '694384'), ('e7eff6', '315b84'), ('f5e6e2', '934a39'), ('e8efdf', '516d2f')]
        result = []
        for index in range(count):
            variation = (int(request['operation_id'][:8], 16) + index) % 10
            bg, ink = palettes[variation % len(palettes)]
            if size.get('color_mode') == 'grayscale': bg, ink = 'eeeeee', '333333'
            title = html.escape(brief['concept'][:48]); audience = html.escape(brief['audience'][:54])
            badge = 'MOCK PROFESSIONAL SAMPLE' if professional else 'MOCK SKETCH'
            cols = 1 + variation % 3; items = ''
            for cell in range(6):
                x = 24 + (cell % cols) * (272 / cols); y = 132 + (cell // cols) * (220 / ((6+cols-1)//cols))
                w = 258 / cols; h = 190 / ((6+cols-1)//cols)
                fill = f'#{ink}' if variation % 2 else 'none'
                shape = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{4+variation}" fill="{fill}" stroke="#{ink}" opacity="0.2"/>'
                shape += f'<circle cx="{x+w/2}" cy="{y+h/2}" r="{min(w,h)/5}" fill="none" stroke="#{ink}" stroke-width="2"/>'
                items += shape
            positive = len(request['accepted']); negative = len(request['rejected'])
            body = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 320 420"><rect width="320" height="420" fill="#{bg}"/><rect x="0" y="0" width="320" height="8" fill="#{ink}"/><text x="24" y="35" font-size="10" fill="#{ink}">{badge} {index+1}</text><text x="24" y="68" font-size="14" fill="#{ink}">{title}</text><text x="24" y="95" font-size="10" fill="#{ink}">{audience}</text>{items}<text x="24" y="384" font-size="9" fill="#{ink}">Direction {variation+1} · references +{positive} / −{negative}</text><text x="24" y="404" font-size="9" fill="#{ink}">Workflow sample · provider selection pending</text></svg>'
            result.append(Asset(body.encode(), 'image/svg+xml', f'Direction {index+1}'))
        return result


def checked_asset(asset):
    if not isinstance(asset, Asset) or not isinstance(asset.label, str) or len(asset.label) > 200:
        raise Invalid('A bounded, labeled asset is required')
    if not isinstance(asset, Asset) or not isinstance(asset.content, bytes) or len(asset.content) > 6_000_000:
        raise Invalid('Bounded image required')
    if asset.media_type == 'image/png':
        import struct
        if len(asset.content)<33 or asset.content[:8]!=b'\x89PNG\r\n\x1a\n' or asset.content[12:16]!=b'IHDR':raise Invalid('PNG required')
        width,height=struct.unpack('>II',asset.content[16:24])
        if not 64<=width<=8192 or not 64<=height<=8192 or b'IEND' not in asset.content[-20:]:raise Invalid('Bounded complete PNG required')
        return asset
    if asset.media_type != 'image/svg+xml' or len(asset.content)>1_000_000:raise Invalid('Supported image required')
    if b'<!' in asset.content or b'<?' in asset.content: raise Invalid('SVG declarations forbidden')
    try: root = ElementTree.fromstring(asset.content)
    except ElementTree.ParseError: raise Invalid('Invalid SVG') from None
    tags = {'svg', 'g', 'rect', 'circle', 'ellipse', 'line', 'path', 'polyline', 'polygon', 'text', 'tspan'}
    attrs = {'width', 'height', 'viewBox', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'd', 'points',
             'fill', 'stroke', 'stroke-width', 'opacity', 'font-size', 'font-family', 'text-anchor', 'transform'}
    if root.tag != '{http://www.w3.org/2000/svg}svg': raise Invalid('SVG root required')
    for node in root.iter():
        if node.tag.removeprefix('{http://www.w3.org/2000/svg}') not in tags or set(node.attrib) - attrs:
            raise Invalid('Unsupported SVG element or attribute')
        if any(re.search(r'url\s*\(|https?:|javascript:|data:', v, re.I) for v in node.attrib.values()):
            raise Invalid('External SVG resources forbidden')
    return asset


class FileBroker:
    """Durable local human-notification inbox, with idempotent publication."""
    name='file'
    def __init__(self, root): self.root = Path(root)
    def publish(self, message):
        path = self.root / (message['event_id']+'.json')
        if path.exists() and digest(read(path)) != digest(message): raise Conflict('Broker identity collision')
        if not path.exists(): write(path, message)
        return {'provider': self.name, 'status': 'recorded', 'event_id': message['event_id']}


class MockBroker(FileBroker):
    name='mock-broker'


class BlockedListing:
    def request_listing(self, approved):
        return {'status': 'blocked_not_wired', 'etsy_api_called': False,
                'message': 'Final approval saved. Etsy listing awaits Studio finalization.'}
