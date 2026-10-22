import requests, time, json, datetime
A='http://127.0.0.1:8000/api/v1'
s=requests.Session(); s.post(A+'/auth/login',json={'username':'admin','password':'admin123'})
rows=[]
for i in range(7):
    t=datetime.datetime.now().isoformat(timespec='seconds')
    al=s.get(A+'/alarms?limit=200',timeout=10).json()
    wo=s.get(A+'/work-orders?limit=1',timeout=10).json()
    items=al.get('items',[])
    open_alarms=[a for a in items if not a.get('closed_at')]
    from collections import Counter
    c=Counter((a['robot_id'],a['metric']) for a in open_alarms)
    rows.append({'t':t,'total':al.get('total'),'open':len(open_alarms),
                 'wo_total':wo.get('total'),'top':c.most_common(8),
                 'latest':[(a['id'],a['robot_id'],a['metric'],a['started_at'],a['message'][:40]) for a in items[:3]]})
    print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    time.sleep(30)
json.dump(rows,open('scripts/qa_state_sync/alarm_watch.json','w'),ensure_ascii=False,indent=2)
