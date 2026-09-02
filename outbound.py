"""Per-config direct/HTTP/HTTPS/SOCKS5 outbound connector."""
import asyncio,base64,ipaddress,ssl
from urllib.parse import unquote,urlsplit
import proxy_repository as repo
_dialer=asyncio.open_connection;_tuner=None
def set_dialer(fn):
 global _dialer;_dialer=fn
def set_tuner(fn):
 global _tuner;_tuner=fn
def _tune(w):
 if _tuner:
  try:_tuner(w)
  except Exception:pass
async def _dial(h,p):return await _dialer(h,p)
def parse_proxy_url(v):
 p=urlsplit(repo.validate_url(v));return {"scheme":p.scheme,"hostname":p.hostname,"port":p.port,"username":unquote(p.username or ""),"password":unquote(p.password or "")}
def _target(h,p):
 h=h.strip('[]')
 try:
  ip=ipaddress.ip_address(h);b=(b'\x01' if ip.version==4 else b'\x04')+ip.packed
 except ValueError:
  x=h.encode('idna');b=b'\x03'+bytes([len(x)])+x
 return b+p.to_bytes(2,'big')
async def _socks(target,port,first,p):
 r,w=await _dial(p['hostname'],p['port']);_tune(w)
 try:
  auth=bool(p['username'] or p['password']);w.write(b'\x05\x02\x00\x02' if auth else b'\x05\x01\x00');await w.drain();reply=await r.readexactly(2)
  if reply[1]==2:
   u=p['username'].encode();pw=p['password'].encode();w.write(b'\x01'+bytes([len(u)])+u+bytes([len(pw)])+pw);await w.drain()
   if (await r.readexactly(2))[1]:raise OSError('SOCKS auth failed')
  elif reply[1]:raise OSError('SOCKS method failed')
  w.write(b'\x05\x01\x00'+_target(target,port));await w.drain();head=await r.readexactly(4)
  if head[1]:raise OSError('SOCKS connect failed')
  if head[3]==1:await r.readexactly(6)
  elif head[3]==4:await r.readexactly(18)
  elif head[3]==3:await r.readexactly((await r.readexactly(1))[0]+2)
  if first:w.write(first);await w.drain()
  return r,w
 except BaseException:w.close();raise
async def _connect(target,port,first,p):
 if p['scheme']=='https':
  ctx=ssl.create_default_context();r,w=await asyncio.open_connection(p['hostname'],p['port'],ssl=ctx,server_hostname=p['hostname'])
 else:r,w=await _dial(p['hostname'],p['port'])
 _tune(w)
 try:
  h=target.strip('[]');authority=(f'[{h}]' if ':' in h else h)+f':{port}';lines=[f'CONNECT {authority} HTTP/1.1',f'Host: {authority}','Proxy-Connection: keep-alive']
  if p['username'] or p['password']:lines.append('Proxy-Authorization: Basic '+base64.b64encode((p['username']+':'+p['password']).encode()).decode())
  w.write(('\r\n'.join(lines)+'\r\n\r\n').encode());await w.drain();head=await asyncio.wait_for(r.readuntil(b'\r\n\r\n'),10)
  if head.split(b'\r\n',1)[0].split()[1]!=b'200':raise OSError('CONNECT rejected')
  if first:w.write(first);await w.drain()
  return r,w
 except BaseException:w.close();raise
async def _endpoint(link):
 if not isinstance(link,dict):return None
 mode=link.get('exit_proxy_mode','direct')
 if mode=='repository':
  x=await repo.resolve(link.get('proxy_id'));return x.endpoint if x else None
 if mode=='custom':
  try:return repo.validate_url(link.get('custom_proxy'))
  except ValueError:return None
async def open_outbound(address,port,first_packet=None,*,link=None,uuid=''):
 endpoint=await _endpoint(link)
 if not endpoint:
  r,w=await _dial(address,port);_tune(w);return r,w,False
 try:
  p=parse_proxy_url(endpoint);r,w=await (_socks(address,port,first_packet,p) if p['scheme']=='socks5' else _connect(address,port,first_packet,p));return r,w,bool(first_packet)
 except BaseException:
  r,w=await _dial(address,port);_tune(w);return r,w,False
