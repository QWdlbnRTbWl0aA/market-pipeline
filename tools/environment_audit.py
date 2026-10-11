"""Publication privacy rules. Local inventories stay outside Git and never print values."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess

DOCUMENTATION = tuple(ipaddress.ip_network(value) for value in
                      ('192.0.2.0/24','198.51.100.0/24','203.0.113.0/24','2001:db8::/32'))
IPV4 = re.compile(rb'(?<![A-Za-z0-9_.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![A-Za-z0-9_.])')
IPV6 = re.compile(rb'(?<![A-Za-z0-9_:])[A-Fa-f0-9:]{2,}(?:\.[0-9.]+)?(?:%[A-Za-z0-9_-]+)?(?![A-Za-z0-9_:])')
LOCAL_DNS = re.compile(rb'(?i)\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:ts\.net|local|lan|internal)\b')
DNS = re.compile(rb'(?i)\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:com|net|org|cloud|local|lan|internal)\b')
URL_HOST = re.compile(rb'(?i)\b(?:https?://|ssh://)([A-Za-z0-9_.-]+)')
PUBLIC_DOMAINS = ('github.com','githubusercontent.com','openai.com','etsy.com','etsystatic.com','w3.org','gmail.com','ietf.org','iana.org','captcha-delivery.com','datadome.co')
EXAMPLE_DOMAINS = ('example.com','example.net','example.org')
PATH = re.compile(rb'(?<![A-Za-z0-9_:/])/(?:home|Users|root|mnt|media|srv|workspace|workspaces|opt|var/lib|etc|run/user|private|Volumes|usr/local)(?:/[A-Za-z0-9_.$~{}+-]+)*')
WINDOWS_HOME = re.compile(rb'(?i)\b[A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+[^\s\x22\x27<>]+')
PORTABLE = ('/etc/market-pipeline','/etc/systemd/system','/opt/market-pipeline','/var/lib/market-pipeline')


def safe_address(value):
    try: address = ipaddress.ip_address(value.split('%',1)[0])
    except ValueError: return None
    if address.version == 6 and address.ipv4_mapped: return safe_address(str(address.ipv4_mapped))
    return address.is_loopback or address.is_unspecified or any(address.version == net.version and address in net for net in DOCUMENTATION)


def portable_path(value):
    return value in ('/etc','/opt','/var/lib') or any(value == p or value.startswith(p+'/') for p in PORTABLE)


def discover(root=None):
    hosts = {socket.gethostname().lower(),socket.getfqdn().lower()}
    hosts = {h.rstrip('.') for h in hosts if h and h not in ('localhost','localhost.localdomain')}
    addresses = set()
    try:
        result = subprocess.run(['ip','-j','address','show'],capture_output=True,text=True,timeout=5,check=True)
        for interface in json.loads(result.stdout):
            for row in interface.get('addr_info',[]):
                for key in ('local','broadcast'):
                    if row.get(key) and safe_address(row[key]) is False: addresses.add(row[key])
    except (OSError,ValueError,subprocess.SubprocessError):
        for host in hosts:
            try:
                addresses.update(row[4][0] for row in socket.getaddrinfo(host,None) if safe_address(row[4][0]) is False)
            except OSError: pass
    paths = {str(Path.home().resolve())}
    if root: paths.add(str(Path(root).resolve()))
    for name in ('HOME','USERPROFILE','PWD'):
        value=os.environ.get(name)
        if value and os.path.isabs(value) and not portable_path(value): paths.add(value)
    return {'schema_version':1,'hostnames':sorted(hosts),'addresses':sorted(addresses),'paths':sorted(paths)}


def load(path):
    path=Path(path)
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>65536:
            raise ValueError('Environment inventory requires a bounded owner-only regular file')
        value=json.loads(os.read(descriptor,65537))
    finally: os.close(descriptor)
    if set(value)!={'schema_version','hostnames','addresses','paths'} or value['schema_version']!=1:
        raise ValueError('Invalid environment inventory')
    for key in ('hostnames','addresses','paths'):
        if not isinstance(value[key],list) or any(not isinstance(v,str) or len(v)<2 or len(v)>4096 for v in value[key]):
            raise ValueError('Invalid environment inventory fields')
    return value


def context(root=None,path=None):
    current=discover(root)
    configured=path or os.environ.get('MARKET_PIPELINE_ENVIRONMENT_FILE')
    default=Path.home()/'.local'/'state'/'market-pipeline-publication'/'environment.json'
    if configured or default.exists():
        saved=load(configured or default)
        for key in ('hostnames','addresses','paths'):current[key]=sorted(set(current[key]+saved[key]))
    return current


def findings(data,inventory=None):
    normalized=data.replace(b'\\/',b'/');rules=set()
    for match in IPV4.finditer(normalized):
        if safe_address(match.group().decode()) is False: rules.add('non_example_ip_address')
    for match in IPV6.finditer(normalized):
        value=match.group().decode()
        if value.count(':')>=2 and safe_address(value) is False:rules.add('non_example_ip_address')
    if LOCAL_DNS.search(normalized):rules.add('private_dns_hostname')
    for match in DNS.finditer(normalized):
        name=match.group().decode().lower()
        if not any(name == domain or name.endswith('.'+domain) for domain in PUBLIC_DOMAINS+EXAMPLE_DOMAINS):
            rules.add('unapproved_hostname')
    for match in URL_HOST.finditer(normalized):
        name=match.group(1).decode().lower()
        example=name=='localhost' or name.endswith(('.example','.test','.invalid','.localhost'))
        public=any(name==domain or name.endswith('.'+domain) for domain in PUBLIC_DOMAINS+EXAMPLE_DOMAINS)
        if not example and not public and safe_address(name) is not True:rules.add('unapproved_hostname')
    if WINDOWS_HOME.search(normalized):rules.add('personal_absolute_path')
    for match in PATH.finditer(normalized):
        if not portable_path(match.group().decode()):rules.add('personal_absolute_path')
    inventory=inventory or {}
    for value in inventory.get('hostnames',[]):
        pattern=rb'(?<![A-Za-z0-9_-])'+re.escape(value.encode())+rb'(?![A-Za-z0-9_-])'
        if re.search(pattern,normalized,re.IGNORECASE):rules.add('observed_machine_hostname')
    for value in inventory.get('addresses',[]):
        if value.encode() in normalized:rules.add('observed_machine_address')
    for value in inventory.get('paths',[]):
        pattern=re.escape(value.encode())+rb'(?=[/\\\s\x22\x27<>),;\]}\x00]|$)'
        if re.search(pattern,normalized,re.IGNORECASE):rules.add('observed_machine_path')
    return sorted(rules)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    args=parser.parse_args();output=Path(args.output).resolve();root=Path(args.root).resolve()
    if output.is_relative_to(root):raise ValueError('Environment inventory must stay outside the repository')
    value=context(root,output if output.exists() else None)
    output.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as stream:json.dump(value,stream,indent=2);stream.write('\n')
    output.chmod(0o600)
    print(json.dumps({'inventory_saved':True,'hostnames':len(value['hostnames']),'addresses':len(value['addresses']),'paths':len(value['paths'])}))
