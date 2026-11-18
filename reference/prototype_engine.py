import csv,sys,re,collections,difflib
from datetime import datetime,timedelta,date
K=sys.argv[1]
rd=lambda p:list(csv.DictReader(open(K+'/'+p)))
items={r['item_code']:r for r in rd('master_data/item_master.csv')}
sup={r['supplier_id']:r for r in rd('master_data/supplier_master.csv')}
po=rd('master_data/po_history.csv')
for p in po: p['d']=datetime.strptime(p['po_date'],'%Y-%m-%d').date(); p['u']=float(p['unit_price'])
D=lambda s:datetime.strptime(s,'%Y-%m-%d').date()
contracts={r['contract_id']:dict(sup=r['supplier_id'],start=D(r['start_date']),end=D(r['end_date']),cap=float(r['value_cap']),used=float(r['consumed_value']),lines={}) for r in rd('contracts/contract_register.csv')}
for l in rd('contracts/contract_lines.csv'): contracts[l['contract_id']]['lines'][l['item_code']]=float(l['rate'])
contracts['RC-2026-031']=dict(sup='S021',start=D('2026-11-15'),end=D('2027-11-14'),cap=2e6,used=0,lines={'ITM-1036':3537.76,'ITM-1037':2439.01,'ITM-1039':2746.87})
contracts['RC-2026-033']=dict(sup='S035',start=D('2026-11-20'),end=D('2027-11-19'),cap=5e6,used=0,lines={'ITM-1056':64654.36,'ITM-1057':10689.51})
active=lambda s:sup[s]['status']=='Active'
ABBR={'brg':'bearing','hyd':'hydraulic','pneu':'pneumatic','rod':'electrode','welding rod':'welding electrode'}
def norm(s):
    s=s.lower(); s=re.sub(r'\(repeat\)|- urgent|as per sample|for maintenance','',s); s=s.replace('"',' inch')
    s=re.sub(r'[^a-z0-9./]+',' ',s); return ' '.join(ABBR.get(t,t) for t in s.split())
def match(desc):
    n=set(norm(desc).replace('-',' ').split()); best=None
    for c,i in items.items():
        m=set(norm(i['description']).split()); m2=set(re.sub(r'[^a-z0-9./]+',' ',i['description'].lower().replace('-',' ')).split())
        sc=len(n&m2)/max(len(n|m2),1)
        if best is None or sc>best[0]: best=(sc,c)
    return best
def score_dq(s): return float(sup[s]['on_time_pct'])/100+float(sup[s]['quality_rating'])/5
def preferred(item,asof,W):
    lo=asof-timedelta(days=548); L={}
    for p in po:
        if p['item_code']==item and lo<=p['d']<asof and active(p['supplier_id']): L.setdefault(p['supplier_id'],[]).append(p)
    con={}
    for cid,c in contracts.items():
        if item in c['lines'] and c['start']<=asof and active(c['sup']): con.setdefault(c['sup'],[]).append((c['start'],c['lines'][item],cid)); L.setdefault(c['sup'],[])
    out=[]; mx=max([len(v) for v in L.values()]+[1])
    for s,v in L.items():
        last=max([p['d'] for p in v],default=None)
        rec=0 if not last else (1 if (asof-last).days<=90 else .5 if (asof-last).days<=365 else 0)
        if v: lp=max(v,key=lambda p:(p["d"],int(p["po_number"]))); ref=lp['u'];src=lp['po_number']
        else: cc=max(con[s]); ref=cc[1];src=cc[2]
        sc=W[0]*len(v)/mx+W[1]*rec+W[2]*(s in con)+W[3]*float(sup[s]['on_time_pct'])/100+W[4]*float(sup[s]['quality_rating'])/5
        out.append((round(sc,6),s,ref,src,len(v),rec,s in con))
    out.sort(key=lambda x:(-x[0],x[1])); return out
def suggest(item,asof,n,W):
    L=[x[1] for x in preferred(item,asof,W)][:n]
    cat=items[item]['category']
    extra=sorted([s for s in sup if active(s) and cat in sup[s]['categories'].split(';') and s not in L],key=lambda s:(-score_dq(s),s))
    return (L+extra)[:n]
def run(prfile,W=(.3,.25,.2,.15,.1),verbose=False):
    pr=rd(prfile); out={}
    for r in pr:
        r['t']=datetime.strptime(r['created_at'],'%Y-%m-%d %H:%M'); r['nb']=D(r['need_by_date']); r['q']=float(r['quantity'])
        r['key']=(r['pr_no'],int(r['pr_line']))
        if r['item_code'] in items: r['ic']=r['item_code']
        else:
            sc,c=match(r['description']); r['ic']=c if sc>=0.6 else 'NEW'; r['msc']=sc
    pr.sort(key=lambda r:(r['t'],r['pr_no'],int(r['pr_line'])))
    reqs=[]
    for r in pr:
        if r['q']<=0 or r['plant'] not in('PUN1','CHK1'): r['np']=1; continue
        g=None
        if r['ic']!='NEW':
            for q in reqs:
                f=q['lines'][0]
                if q['ic']==r['ic'] and q['plant']==r['plant'] and (r['t'].date()-f['t'].date()).days<=14 and abs((r['nb']-f['nb']).days)<=7: g=q;break
        if g: g['lines'].append(r)
        else: reqs.append(dict(ic=r['ic'],plant=r['plant'],lines=[r]))
    used={c:v['used'] for c,v in contracts.items()}
    pos=[]
    for i,q in enumerate(reqs):
        f=q['lines'][0]; q['id']='REQ-%04d'%(i+1); q['t']=f['t']; dt=f['t'].date(); qty=sum(l['q'] for l in q['lines']); ic=q['ic']
        q['emg']=any(l['urgency']=='Emergency' for l in q['lines']); q['sugg']=[];q['sup']=q['price']=None
        if ic=='NEW':
            q['value']=f['q']*float(f['estimated_unit_price'] or 0); q['route']='NEW_ITEM_SOURCING'; continue
        app=sorted([(c['lines'][ic],cid) for cid,c in contracts.items() if ic in c['lines'] and c['start']<=dt<=c['end'] and active(c['sup'])])
        capex=items[ic]['item_type']=='Capex'
        usable=[(r_,cid) for r_,cid in app if used[cid]+qty*r_<=contracts[cid]['cap']]
        h=[p for p in po if p['item_code']==ic and dt-timedelta(days=365)<=p['d']<dt]
        if usable: price=usable[0][0]; q['psrc']=usable[0][1]
        elif app: price=app[0][0]; q['psrc']=app[0][1]+' (out of ceiling)'
        elif h: lp=max(h,key=lambda p:(p["d"],int(p["po_number"]))); price=lp['u']; q['psrc']='PO '+lp['po_number']
        else: price=float(items[ic]['standard_price']); q['psrc']='std'
        v=q['value']=qty*price; bought=any(active(p['supplier_id']) for p in h)
        pl=preferred(ic,dt,W)
        if capex: q['route']='CAPEX_SOURCING'; q['sugg']=suggest(ic,dt,5,W)
        elif usable:
            q['route']='CONTRACT_PO'; cid=usable[0][1]; used[cid]+=v; q['sup']=contracts[cid]['sup']; q['price']=price
        elif q['emg'] and v<=5e5 and bought and pl: q['route']='EMERGENCY_PO'; q['sup']=pl[0][1]; q['price']=pl[0][2]
        elif v<2e5 and bought and pl: q['route']='SPOT_PO'; q['sup']=pl[0][1]; q['price']=pl[0][2]
        elif v<1e6: q['route']='RFQ'; q['sugg']=suggest(ic,dt,3,W)
        else: q['route']='RFP'; q['sugg']=suggest(ic,dt,5,W)
    n=0
    for q in sorted(reqs,key=lambda q:q['t']):
        if not q['sup']: continue
        P=next((p for p in pos if p['k']==(q['sup'],q['plant'],q['route']) and q['t']-p['t']<=timedelta(hours=24)),None)
        if not P: n+=1; P=dict(k=(q['sup'],q['plant'],q['route']),t=q['t'],id='PO-%04d'%n); pos.append(P)
        q['po']=P['id']
    return pr,reqs
if __name__=='__main__':
    pr,reqs=run('pr_batches/sample_pr_batch.csv')
    by={l['key']:q for q in reqs for l in q['lines']}
    chk=[('PR-26-00019','CONTRACT_PO','S001',137531,'PO-0011'),('PR-26-00045','CONTRACT_PO','S021',26829,'PO-0072'),('PR-26-00004','RFQ','S014;S013;S016',220256,None),('PR-26-00034','CONTRACT_PO','S007',32547,'PO-0003'),('PR-26-00146','SPOT_PO','S024',126472,'PO-0001'),('PR-26-00106','SPOT_PO','S027',156170,'PO-0002'),('PR-26-00088','SPOT_PO','S023',97955,'PO-0023'),('PR-26-00059','EMERGENCY_PO','S014',253184,'PO-0024'),('PR-26-00089','RFQ','S043;S044;S042',336562,None),('PR-26-00050','RFQ','S003;S002;S005',80300,None),('PR-26-00100','RFP','S020;S017;S019;S018',2070780,None),('PR-26-00047','CAPEX_SOURCING','S045;S047;S020;S048;S046',6036704,None),('PR-26-00170','NEW_ITEM_SOURCING','',141100,None),('PR-26-00031','CONTRACT_PO','S007',23227,'PO-0003')]
    for prn,route,s,val,poid in chk:
        q=by[(prn,1)]; got=(q['route'],q['sup'] or ';'.join(q['sugg']),round(q['value']),q.get('po'))
        ok=got==(route,s,val,poid)
        print('OK ' if ok else 'XX ',prn,got,'' if ok else ('expected',route,s,val,poid),[l['pr_no'] for l in q['lines']],q.get('psrc'),q['price'])
    for it in('ITM-1048','ITM-1036','ITM-1016'):
        print(it,[(x[1],x[0],x[4],x[5],x[6]) for x in preferred(it,D('2026-11-01'),(.3,.25,.2,.15,.1))])
    print(collections.Counter(q['route'] for q in reqs),len(reqs),'reqs; not processed',[r['key'] for r in pr if r.get('np')])
    print('NEW:',[(l['pr_no'],l['description'],round(l['msc'],2)) for q in reqs if q['ic']=='NEW' for l in q['lines']])
    print('fuzzy:',[(l['pr_no'],l['description'],l['ic'],round(l['msc'],2)) for l in pr if 'msc' in l and l['ic']!='NEW' and l['msc']<1])
    print('--- first reqs by time')
    for q in sorted(reqs,key=lambda q:q['t'])[:12]: print(q['t'],q['ic'],q['plant'],q['route'],q['sup'],round(q['value']),q.get('po'),[l['pr_no'] for l in q['lines']],q.get('psrc'))
    print('--- emergencies'); 
    for q in reqs:
        if q['emg']: print(q['ic'],q['plant'],q['route'],q['sup'],round(q['value']),[(l['pr_no'],l['urgency']) for l in q['lines']])
    print('--- latest PO (365d) is from non-active supplier, or 1st preferred != latest PO supplier')
    for q in reqs:
        if q['ic']=='NEW':continue
        dt=q['t'].date(); h=[p for p in po if p['item_code']==q['ic'] and dt-timedelta(days=365)<=p['d']<dt]
        if h:
            lp=max(h,key=lambda p:(p['d'],int(p['po_number'])))
            if not active(lp['supplier_id']): print(' latest PO blocked/inactive:',q['ic'],lp['supplier_id'],sup[lp['supplier_id']]['status'],q['route'],[l['pr_no'] for l in q['lines']], 'any active buy:',any(active(p['supplier_id']) for p in h))
    print('--- contract edge cases')
    for q in reqs:
        if q['ic'] in('ITM-1056','ITM-1057','ITM-1036','ITM-1037','ITM-1039','ITM-1052','ITM-1053','ITM-1006','ITM-1007','ITM-1015','ITM-1016','ITM-1019'): print(q['t'],q['ic'],q['plant'],q['route'],q['sup'],round(q['value']),q.get('psrc'),[(l['pr_no'],l['created_at'][5:10]) for l in q['lines']])
    print('--- clubbing boundary: same item+plant pairs not clubbed with created gap 13-15d or need-by gap 6-9d')
    for a in reqs:
        for b in reqs:
            if a is not b and a['ic']==b['ic']!='NEW' and a['plant']==b['plant'] and a['t']<b['t']:
                fa,fb=a['lines'][0],b['lines'][0]; cg=(fb['t'].date()-fa['t'].date()).days; ng=abs((fb['nb']-fa['nb']).days)
                if ng in(7,8) or cg in(14,15): print(' ',a['ic'],fa['pr_no'],fb['pr_no'],'created gap',cg,'needby gap',ng)
    print('--- value near thresholds'); 
    for q in reqs:
        v=q['value']
        if any(abs(v-t)/t<0.03 for t in(2e5,5e5,1e6)): print(' ',q['ic'],round(v,2),q['route'],q['emg'])
    print('--- PO consolidation near 24h'); 
    P=collections.defaultdict(list)
    for q in reqs:
        if q['sup']: P[(q['sup'],q['plant'],q['route'])].append(q)
    for k,v in P.items():
        v.sort(key=lambda q:q['t'])
        for a,b in zip(v,v[1:]):
            g=(b['t']-a['t']).total_seconds()/3600
            if 20<=g<=28: print(' ',k,a['t'],b['t'],round(g,2),a.get('po'),b.get('po'))
    print('POs:',len(set(q.get('po') for q in reqs if q['sup'])))
