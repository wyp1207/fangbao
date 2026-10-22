import requests,time,threading,sys
from concurrent.futures import ThreadPoolExecutor
A='http://127.0.0.1:8000'
S=requests.Session()
for _ in range(5):
    try:
        r=S.post(A+'/api/v1/auth/login',json={'username':'admin','password':'admin123'},timeout=10)
        if r.status_code==200: break
    except Exception as e: print('login retry',e.__class__.__name__,flush=True); time.sleep(3)
C=S.cookies.get_dict(); print('login ok',flush=True)
time.sleep(16)
def one(i):
    t=time.perf_counter()
    try:
        r=requests.get(A+'/api/v1/reports/summary',cookies=C,timeout=25); return (time.perf_counter()-t)*1000,r.status_code
    except Exception: return (time.perf_counter()-t)*1000,-1
stop=False; health=[]
def poll():
    while not stop:
        t=time.perf_counter()
        try: r=requests.get(A+'/health',timeout=4); health.append(((time.perf_counter()-t)*1000,r.status_code))
        except Exception: health.append(((time.perf_counter()-t)*1000,-1))
        time.sleep(0.1)
th=threading.Thread(target=poll,daemon=True); th.start()
with ThreadPoolExecutor(max_workers=20) as ex: res=list(ex.map(one,range(20)))
lat=sorted(x[0] for x in res); codes={c:sum(1 for _,x in res if x==c) for c in set(x for _,x in res)}
print('ROUND1 n=20 p50=%.1f p95=%.1f max=%.1f codes=%s'%(lat[10],lat[18],lat[-1],codes),flush=True)
stop=True; time.sleep(0.2)
print('health n=%d codes=%s max=%.1f'%(len(health),{c:sum(1 for _,x in health if x==c) for c in set(x for _,x in health)},max(x for x,_ in health)),flush=True)
