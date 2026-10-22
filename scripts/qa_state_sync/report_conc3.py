import requests,time,threading
from concurrent.futures import ThreadPoolExecutor
A='http://127.0.0.1:8000'; S=requests.Session(); S.post(A+'/api/v1/auth/login',json={'username':'admin','password':'admin123'}); C=S.cookies.get_dict()
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
for rnd in range(3):
    time.sleep(16)
    with ThreadPoolExecutor(max_workers=20) as ex: res=list(ex.map(one,range(20)))
    lat=sorted(x[0] for x in res); codes={c:sum(1 for _,x in res if x==c) for c in set(x for _,x in res)}
    print('ROUND%d n=20 p50=%.1f p95=%.1f max=%.1f codes=%s'%(rnd+1,lat[10],lat[18],lat[-1],codes),flush=True)
stop=True; time.sleep(0.2); hc=health
print('health n=%d codes=%s max=%.1f p95=%.1f'%(len(hc),{c:sum(1 for _,x in hc if x==c) for c in set(x for _,x in hc)},max(x for x,_ in hc),sorted(x for x,_ in hc)[int(len(hc)*.95)]),flush=True)
