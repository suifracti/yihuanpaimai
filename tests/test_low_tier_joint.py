import json,subprocess,unittest,os
from pathlib import Path
ROOT=Path(os.environ.get('NTE_TEST_RUNTIME_ROOT',str(Path(__file__).resolve().parents[1])))

class LowTierJointTests(unittest.TestCase):
    def test_known_low_names_candidates_and_repeated_copies(self):
        script=r"""
        const e=require('./core/auction_engine_v06.js'),cat=e.effectiveCatalog({});
        const area=x=>x[2].split('x').map(Number).reduce((a,b)=>a*b,1);
        const rows=[];
        for(const color of ['blue','green','white']) {
          const a=cat[color][0],b=cat[color].find(x=>area(x)!==area(a));
          const key='known'+color[0].toUpperCase()+color.slice(1);
          const base={q:1,goldCount:1,purple:0,redCount:0,avg:60040,knownGold:'算力面包'};
          const cases=[
            [{[key]:a[0],[color+'Count']:1,[color+'Grid']:area(a)},true],
            [{[key]:a[0],[color+'Count']:1,[color+'Grid']:area(b)},false],
            [{[key]:a[0]+'/'+b[0],[color+'Count']:1,[color+'Grid']:area(b)},true],
            [{[key]:a[0]+'*3',[color+'Count']:3,[color+'Grid']:area(a)*3,[color+'Avg']:a[1]},true],
            [{[key]:a[0]+'+'+a[0],[color+'Count']:1},false],
            [{[key]:a[0]+'/'+b[0]+'+'+a[0], [color+'Count']:1},false],
            [{[key]:a[0]+'/'+b[0]+'+'+a[0], [color+'Count']:2,[color+'Grid']:area(a)+area(b),[color+'Avg']:Math.floor((a[1]+b[1])/2)},true],
            [{[key]:a[0]+'*3',totalItems:3},false],
            [{[key]:a[0]+'*3',totalItems:4},true],
            [{[key]:'__invalid_catalog_name__',[color+'Count']:1},false],
            [{[key]:a[0]+'*0',[color+'Count']:1},false],
            [{[key]:String(a[1]),[color+'Count']:1,[color+'Grid']:area(a)},true]
          ];
          for(const [fields,expected] of cases) {
            const ctx={...base,...fields},before=JSON.stringify(ctx);
            rows.push({ctx,expected,actual:e.solveExactStatesSync(ctx).states.length>0,unchanged:before===JSON.stringify(ctx)});
          }
        }
        console.log(JSON.stringify(rows));
        """
        rows=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,text=True,encoding='utf-8',timeout=30))
        for row in rows:
            with self.subTest(ctx=row['ctx']):
                self.assertEqual(row['actual'],row['expected'],row)
                self.assertTrue(row['unchanged'],row)
                run=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':row['ctx'],'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(run.returncode,0,run.stderr)
                result=json.loads(run.stdout)
                self.assertEqual(bool(result['exactStates']),row['expected'],row)
                self.assertEqual(bool(result['expandedStates']),row['expected'],row)

    def test_real_catalog_joint_constraints_in_production_runtime(self):
        catalog=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',"console.log(JSON.stringify(require('./core/auction_engine_v06.js').effectiveCatalog({})))"],cwd=ROOT,text=True,encoding='utf-8'))
        base={'q':1,'goldCount':1,'purple':0,'redCount':0,'avg':60040,'knownGold':'算力面包'}
        for color in ('blue','green','white'):
            items=catalog[color]
            area=lambda row:__import__('math').prod(map(int,row[2].split('x')))
            first=next(row for row in items if sum(x[1]==row[1] for x in items)==1)
            other=next(row for row in items if area(row)!=area(first))
            cases=[({color+'Count':1,color+'Grid':area(first),color+'Avg':first[1]},True),
                   ({color+'Count':1,color+'Grid':area(other)},True),
                   ({color+'Count':1,color+'Avg':first[1]},True),
                   ({color+'Count':1,color+'Grid':area(other),color+'Avg':first[1]},False),
                   ({color+'Count':3,color+'Grid':area(first)*3,color+'Avg':first[1]},True),
                   ({color+'Count':0,color+'Avg':first[1]},False),
                   ({color+'Count':1,color+'Avg':True},False)]
            for fields,expected in cases:
                with self.subTest(color=color,fields=fields):
                    result=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':{**base,**fields},'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
                    self.assertEqual(result.returncode,0,result.stderr)
                    payload=json.loads(result.stdout)
                    self.assertEqual(bool(payload['exactStates']),expected)
                    self.assertEqual(bool(payload['expandedStates']),expected)

    def test_unknown_low_counts_are_jointly_bounded_without_mutating_input(self):
        script=r"""
        const e=require('./core/auction_engine_v06.js'),cat=e.effectiveCatalog({});
        const area=x=>x[2].split('x').map(Number).reduce((a,b)=>a*b,1);
        const choose=k=>cat[k].find(x=>cat[k].filter(y=>y[1]===x[1]).length===1);
        const blue=choose('blue'),green=choose('green');
        const wrong=cat.blue.find(x=>area(x)!==area(blue));
        const base={q:1,goldCount:1,purple:0,redCount:0,avg:60040,knownGold:'算力面包'};
        const cases=[
          [{totalItems:2,greenCount:0,whiteCount:0,blueAvg:blue[1],blueGrid:area(blue)},true],
          [{totalItems:2,greenCount:0,whiteCount:0,blueAvg:blue[1],blueGrid:area(wrong)},false],
          [{totalItems:3,greenCount:0,whiteCount:0,blueAvg:blue[1],blueGrid:area(blue)*2},true],
          [{totalItems:2,whiteCount:0,blueAvg:blue[1],greenAvg:green[1],blueGrid:area(blue),greenGrid:area(green)},false],
          [{totalItems:3,whiteCount:0,blueAvg:blue[1],greenAvg:green[1],blueGrid:area(blue),greenGrid:area(green)},true],
          [{blueGrid:0,blueAvg:blue[1]},false],
          [{blueGrid:area(blue),blueAvg:blue[1]},true],
          [{blueAvg:blue[1]},true]
        ];
        console.log(JSON.stringify(cases.map(([fields,expected])=>{
          const ctx={...base,...fields},before=JSON.stringify(ctx),states=e.solveExactStatesSync(ctx).states;
          return {fields,expected,actual:states.length>0,unchanged:before===JSON.stringify(ctx)};
        })));
        """
        rows=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,text=True,encoding='utf-8',timeout=30))
        for row in rows:
            self.assertEqual(row['actual'],row['expected'],row)
            self.assertTrue(row['unchanged'],row)
            result=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':{'q':1,'goldCount':1,'purple':0,'redCount':0,'avg':60040,'knownGold':'算力面包',**row['fields']},'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            payload=json.loads(result.stdout)
            self.assertEqual(bool(payload['exactStates']),row['expected'],row)
            self.assertEqual(bool(payload['expandedStates']),row['expected'],row)

    def test_canonical_adapter_live_transport_and_clear_reach_runtime(self):
        from current_match import CurrentMatch
        from v06_adapter import canonical_to_v06_solver_input
        from live_shadow import _solver_ctx, _profile_cache_key
        from live_match_control import LiveMatchControl
        catalog=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',"console.log(JSON.stringify(require('./core/auction_engine_v06.js').effectiveCatalog({})))"],cwd=ROOT,text=True,encoding='utf-8'))
        for color in ('blue','green','white'):
            items=catalog[color]
            area=lambda row:__import__('math').prod(map(int,row[2].split('x')))
            item=next(x for x in items if sum(y[1]==x[1] for y in items)==1)
            wrong=next(x for x in items if area(x)!=area(item))
            match=CurrentMatch()
            facts={'q':1,'goldCount':1,'purpleCount':0,'redCount':0,'goldAvg':60040,'knownGold':'算力面包',color+'Count':1,color+'Avg':item[1],color+'Grid':area(item)}
            match.apply_facts(facts,source='manual',intent='confirm')
            adapted=canonical_to_v06_solver_input(match.to_canonical())
            for suffix in ('Count','Avg','Grid'):
                key=color+suffix
                self.assertEqual(adapted[key],facts[key])
                self.assertEqual(adapted['publicInfo'][key],facts[key])
            control=LiveMatchControl();control.match_id=match.id
            previous=None
            for value,expected in ((area(item),True),(area(wrong),False),(None,True)):
                control.overrides={color+'Grid':value}
                corrected=control.apply_to_frame(adapted,match)
                context=_solver_ctx(corrected)
                self.assertEqual(context[color+'Grid'],value)
                self.assertEqual(context['publicInfo'][color+'Grid'],value)
                key=_profile_cache_key(corrected,0)
                self.assertNotEqual(key,previous);previous=key
                result=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':context,'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                payload=json.loads(result.stdout)
                self.assertEqual(bool(payload['exactStates']),expected,(color,value,payload))
                self.assertEqual(bool(payload['expandedStates']),expected)

    def test_low_count_and_area_cannot_use_different_combinations(self):
        script=r"""
        const e=require('./core/auction_engine_v06.js'),cat=e.effectiveCatalog({});
        const area=x=>x[2].split('x').map(Number).reduce((a,b)=>a*b,1);
        const choose=k=>cat[k].find(x=>cat[k].filter(y=>y[1]===x[1]).length===1);
        const b=choose('blue'),g=choose('green'),sum=2+area(b)+area(g);
        const blueAreas=new Set(cat.blue.map(area));let gap=1;while(blueAreas.has(gap))gap++;
        const base={q:1,goldCount:1,purple:0,redCount:0,avg:60040,knownGold:'算力面包'};
        const pair={blueCount:1,greenCount:1,whiteCount:0,blueAvg:b[1],greenAvg:g[1],totalItems:3};
        const cases=[
          [{...pair,totalGrid:sum},true], [{...pair,totalGrid:sum+1},false],
          [{...pair,blueCount:null,greenCount:null,totalGrid:sum},true],
          [{...pair,blueCount:null,greenCount:null,totalGrid:sum+1},false],
          [{blueCount:1,greenCount:0,whiteCount:0,totalItems:2,totalGrid:2+gap},false],
          [{blueCount:1,greenCount:0,whiteCount:0,totalItems:2,totalGrid:2+area(b)},true],
          [{...pair,totalGrid:null},true]
        ];console.log(JSON.stringify(cases.map(([fields,expected])=>({fields,expected,actual:e.solveExactStatesSync({...base,...fields}).states.length>0}))));
        """
        rows=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,text=True,encoding='utf-8',timeout=30))
        for row in rows:
            self.assertEqual(row['actual'],row['expected'],row)
            ctx={'q':1,'goldCount':1,'purple':0,'redCount':0,'avg':60040,'knownGold':'算力面包',**row['fields']}
            run=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':ctx,'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(run.stdout)
            self.assertEqual(bool(result['exactStates']),row['expected'],row)
            self.assertEqual(bool(result['expandedStates']),row['expected'],row)

    def test_unknown_purple_red_area_uses_same_named_catalog_copies(self):
        script=r"""
        const e=require('./core/auction_engine_v06.js'),c=e.effectiveCatalog({});
        const area=x=>x[2].split('x').map(Number).reduce((a,b)=>a*b,1);
        const unique=k=>c[k].find(x=>c[k].filter(y=>y[1]===x[1]).length===1);
        const p=unique('purple'),r=unique('red'),b=unique('blue');
        const base={q:3,goldCount:1,purple:1,redCount:1,avg:60040,knownGold:'算力面包',knownPurple:p[0],knownRed:r[0],blueCount:1,blueAvg:b[1],greenCount:0,whiteCount:0,totalItems:4};
        const total=2+area(p)+area(r)+area(b);
        const cases=[
          [{...base,totalGrid:total},true], [{...base,totalGrid:total+1},false],
          [{...base,totalGrid:total,purpleGrid:area(p)},true],
          [{...base,totalGrid:total,redGrid:area(r)+1},false],
          [{...base,totalGrid:total,purpleAvg:p[1]},true],
          [{...base,totalGrid:null},true],
          [{...base,q:4,purple:2,knownPurple:p[0]+'+'+p[0],totalItems:5,totalGrid:total+area(p)},true]
        ];console.log(JSON.stringify(cases.map(([ctx,expected])=>({ctx,expected,actual:e.solveExactStatesSync(ctx).states.length>0}))));
        """
        rows=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,text=True,encoding='utf-8',timeout=30))
        for row in rows:
            self.assertEqual(row['actual'],row['expected'],row)
            run=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':row['ctx'],'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            result=json.loads(run.stdout)
            self.assertEqual(bool(result['exactStates']),row['expected'],row)
            self.assertEqual(bool(result['expandedStates']),row['expected'],row)
