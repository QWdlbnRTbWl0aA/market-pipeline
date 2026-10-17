"""Separate systemd services. No unit starts or requires another business stage."""
SPECS = {
 'collector': ('collector','/var/lib/market-pipeline/collector/config.json',8090,
               ('collector',), 'etsy.env'),
 'search-refiner': ('search-refiner','/etc/market-pipeline/analyzer.json',None,
                    ('analyzer','paid-ledger','local-cache'), 'openai.env'),
 'market-analyst': ('market-analyst','/etc/market-pipeline/analyzer.json',None,
                    ('analyzer','paid-ledger','local-cache'), 'openai.env'),
 'controller': ('controller','/etc/market-pipeline/controller.json',8094,
                 ('controller','paid-ledger'), None),
 'product': ('product','/etc/market-pipeline/product.json',8093,('product',),None),
 'studio': ('studio','/etc/market-pipeline/studio.json',8096,('studio',),None)
}


def render(name, user='market-pipeline', mail=False, product_paid=False):
    service, config, port, writable, credential = SPECS[name]
    if name=='product' and product_paid:writable=(*writable,'paid-ledger')
    args = f'{service} --config {config}'
    if port: args += f' --port {port}'
    if name == 'collector': args += ' --bind 0.0.0.0'
    rows = ['[Unit]',f'Description=Market pipeline: {name}',
            'After=network.target','StartLimitIntervalSec=300','StartLimitBurst=3','',
            '[Service]','Type=simple',f'User={user}',f'Group={user}',
            'WorkingDirectory=/opt/market-pipeline/current',
            f'ExecStart=/usr/bin/python3 /opt/market-pipeline/current/deploy/launch.py {args}',
            'Restart=on-failure','RestartSec=10','TimeoutStopSec=600','KillSignal=SIGTERM',
            'KillMode=control-group','UMask=0077','NoNewPrivileges=yes',
            'ProtectSystem=strict','ProtectHome=yes','PrivateTmp=yes','PrivateDevices=yes',
            'ProtectKernelTunables=yes','ProtectKernelModules=yes','ProtectControlGroups=yes',
            'RestrictSUIDSGID=yes','LockPersonality=yes','CapabilityBoundingSet=',
            'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6',
            'InaccessiblePaths=/etc/market-pipeline/credentials',
            'ReadWritePaths='+' '.join('/var/lib/market-pipeline/'+p for p in writable),
            'StandardOutput=journal','StandardError=journal']
    if credential: rows.append(f'LoadCredential={credential}:/etc/market-pipeline/credentials/{credential}')
    if name=='product' and product_paid:rows.append('LoadCredential=openai.env:/etc/market-pipeline/credentials/openai.env')
    if mail and name in ('market-analyst','product'):rows.append('LoadCredential=gmail_smtp.env:/etc/market-pipeline/credentials/gmail_smtp.env')
    if name == 'collector': rows.append('EnvironmentFile=-/etc/market-pipeline/dashboard.env')
    rows += ['', '[Install]','WantedBy=multi-user.target','']
    return '\n'.join(rows)
