import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {computeBoundsTree,disposeBoundsTree,acceleratedRaycast} from './vendor/three-mesh-bvh.js';
import {dimensions,distance,polygonArea} from './measurements.js';
import {initMap} from './mpunav-ui.js';
THREE.BufferGeometry.prototype.computeBoundsTree=computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree=disposeBoundsTree;
THREE.Mesh.prototype.raycast=acceleratedRaycast;
const $=id=>document.getElementById(id);
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x131416);renderer.localClippingEnabled=true;
$('viewport').prepend(renderer.domElement);
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(45,1,.01,1000),controls=new OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;camera.position.set(5,4,5);
scene.add(new THREE.HemisphereLight(0xffffff,0x8796a5,2));
const grid=new THREE.GridHelper(30,30,0x53616d,0x303e49);scene.add(grid);
const marks=new THREE.Group();scene.add(marks);
let project=null,jobs=[],current=null,mode='mesh',model=null,before=null,after=null,cache=new Map(),request=0,measurement=null,picked=[],drag=null,selection=null,busyUpload=false;
const ray=new THREE.Raycaster();ray.firstHitOnly=true;ray.params.Points.threshold=.02;
const vector=new THREE.Vector3(),pointer=new THREE.Vector2();
function error(text){$('error').textContent=text;$('error').hidden=!text}
async function api(path,options={}){const r=await fetch(path,options),d=await r.json();if(!r.ok)throw new Error(d.error||'Ошибка сервера');return d}
const post=(path,data)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function dispose(root){root.traverse(o=>{o.geometry?.disposeBoundsTree?.();o.geometry?.dispose();const materials=o.material?(Array.isArray(o.material)?o.material:[o.material]):[];for(const m of materials){m.map?.dispose();m.dispose()}})}
function clearSceneModels(){for(const root of cache.values()){scene.remove(root);dispose(root)}cache.clear();model=before=after=null;$('empty').hidden=false;$('variant').textContent='Выбери или импортируй скан';$('modelStats').textContent='Метры · Y вверх';for(const id of ['compareLine','compareControl','beforeLabel','afterLabel','heatLegend'])$(id).hidden=true}
new ResizeObserver(()=>{const w=$('viewport').clientWidth,h=$('viewport').clientHeight;if(!w||!h)return;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix()}).observe($('viewport'));
renderer.setAnimationLoop(()=>{
 controls.update();const w=$('viewport').clientWidth,h=$('viewport').clientHeight;
 if(mode==='compare'&&before&&after){
  const split=Math.round(w*Number($('compareSlider').value)/100);renderer.setScissorTest(true);
  before.visible=true;after.visible=false;renderer.setScissor(0,0,split,h);renderer.render(scene,camera);
  before.visible=false;after.visible=true;renderer.setScissor(split,0,w-split,h);renderer.render(scene,camera);renderer.setScissorTest(false);
  $('compareLine').style.left=split+'px';before.visible=true;
 }else renderer.render(scene,camera);
});
function fit(top=false){if(!model)return;const box=new THREE.Box3().setFromObject(model),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());controls.target.copy(center);camera.up.set(0,top?0:1,top?-1:0);const v=THREE.MathUtils.degToRad(camera.fov),h=2*Math.atan(Math.tan(v/2)*camera.aspect);const d=Math.max(size.length()/2,1)/Math.sin(Math.min(v,h)/2)*1.06;camera.position.copy(center).addScaledVector(top?new THREE.Vector3(0,1,.00001):new THREE.Vector3(1,.7,1).normalize(),d);camera.far=Math.max(100,d*10);camera.updateProjectionMatrix();controls.update();grid.position.y=box.min.y-.02}
async function getModel(file){
 const key=current.id+'/'+file;if(cache.has(key))return cache.get(key);
 const gltf=await new GLTFLoader().loadAsync(`/data/${key}?v=${current.report.processingVersion||0}`);
 gltf.scene.traverse(o=>{if(o.isMesh){o.geometry.computeBoundsTree();o.material.side=THREE.DoubleSide}if(o.isPoints){o.material.size=.012;o.material.sizeAttenuation=true}});
 gltf.scene.visible=false;scene.add(gltf.scene);cache.set(key,gltf.scene);return gltf.scene;
}
function meshIn(root){let found;root.traverse(o=>{if(!found&&o.isMesh)found=o});return found}
async function differenceModel(){
 const key=current.id+'/difference';if(cache.has(key))return cache.get(key);
 const a=meshIn(await getModel('mesh.glb')),b=meshIn(await getModel('straightened.glb'));
 if(!a||!b||a.geometry.attributes.position.count!==b.geometry.attributes.position.count)throw new Error('Сетки несовместимы для карты изменений');
 const geometry=b.geometry.clone(),p=a.geometry.attributes.position,q=b.geometry.attributes.position,colors=new Float32Array(p.count*3),color=new THREE.Color();
 for(let i=0;i<p.count;i++){const d=Math.hypot(p.getX(i)-q.getX(i),p.getY(i)-q.getY(i),p.getZ(i)-q.getZ(i))/.005;const t=Math.min(1,d);color.set(t<.02?0x53616d:t<.5?0x39b88c:0xe3ba51);if(t>.85)color.set(0xe36450);color.toArray(colors,i*3)}
 geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));geometry.computeBoundsTree();
 const result=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.DoubleSide}));result.visible=false;scene.add(result);cache.set(key,result);return result;
}
async function show(nextMode='mesh',reset=false){
 if(!current?.report||(!current.report.mesh&&!current.report.pointCloud))return;
 const ticket=++request;error('');
 try{
  let target,original,processed;
  if(['corrected','compare','difference'].includes(nextMode)&&(!current.report.straightened||current.report.processingVersion!==2))throw new Error('Сначала выполни обработку v2');
  if(nextMode==='points'&&!current.report.pointCloud)throw new Error('Облако LAS ещё не обработано');
  if(nextMode==='old'&&!current.report.legacyResult)throw new Error('Архивная обработка v1 отсутствует');
  if(nextMode==='compare'){original=await getModel('mesh.glb');processed=await getModel('straightened.glb');target=original}
  else if(nextMode==='difference')target=await differenceModel();
  else target=await getModel(nextMode==='corrected'?'straightened.glb':nextMode==='points'||!current.report.mesh?'points.glb':nextMode==='old'?'previous-v1.glb':'mesh.glb');
  if(ticket!==request)return;
  for(const root of cache.values())root.visible=false;
  model=target;model.visible=true;before=original;after=processed;mode=nextMode;
  $('viewMode').value=mode;$('empty').hidden=true;
  for(const id of ['compareLine','compareControl','beforeLabel','afterLabel'])$(id).hidden=mode!=='compare';
  $('heatLegend').hidden=mode!=='difference';
  $('variant').textContent={mesh:'Исходная модель',corrected:'Обработка v2 · ограниченные правки',compare:'Один ракурс · два результата',difference:'Сдвиг вершин относительно исходного GLB',points:'Облако точек LAS',old:'Архив v1 · содержит дефекты'}[mode];
  $('variant').dataset.ready=mode;
  if(reset)fit();wire();updateInspector();
 }catch(e){error(e.message);$('viewMode').value=mode}
}
function wire(){for(const root of cache.values())root.traverse(o=>{if(o.isMesh)o.material.wireframe=$('wire').checked})}
function updateInspector(){
 const r=current?.report||{},c=r.planarAnalysis?.changes;
 $('modelStats').textContent=current?`${current.name} · метры`: 'Метры · Y вверх';
 $('changes').textContent=c?`${c.movedVertices.toLocaleString('ru')} вершин изменены\nМаксимальный сдвиг: ${c.maximumShiftMm.toFixed(2)} мм\nПредельный наклон: ${(c.maximumNormalChangeDegrees||0).toFixed(2)}°\nСогласованных швов: ${c.weldedSeamGroups||0}\nGPU: ${r.planarAnalysis.backend||'CPU'}`:'Обработка v2 ещё не выполнена';
 const align=r.las?.alignment;$('alignment').textContent=align?`Медиана расстояния облака до вершин сетки: ${align.medianDistanceMm.toFixed(1)} мм. Это согласование двух экспортов, а не точность относительно реального объекта.`:r.pointCloud?'LAS без пары GLB: локальные координаты, Y вверх.':'Данные совмещения отсутствуют';
 $('exports').replaceChildren();
 for(const name of (r.availableFiles||[]).filter(n=>n.endsWith('.glb')||n.endsWith('.ply'))){const a=document.createElement('a');a.textContent=name.replace('.glb','').replace('.ply',' PLY');a.href=`/data/${current.id}/${name}`;a.download=name;$('exports').append(a)}
 $('plan').hidden=!r.planComparison;if(r.planComparison)$('plan').href=`/data/${current.id}/${r.planComparison}`;
 $('process').disabled=!current||current.state==='running';$('processCompact').disabled=$('process').disabled;
}
async function selectJob(job){const same=current?.id===job.id;if(!same){++request;clearSceneModels();clearMeasurement()}current=job;renderJobs();updateInspector();await show(job.report.mesh?'mesh':job.report.pointCloud?'points':'mesh',!same)}
function renderJobs(){
 $('scanSelect').replaceChildren();for(const j of jobs){const option=document.createElement('option');option.value=j.id;option.textContent=j.name;$('scanSelect').append(option)}if(current)$('scanSelect').value=current.id;
 $('jobs').replaceChildren();for(const j of jobs){const button=document.createElement('button');button.className='job'+(j.id===current?.id?' selected':'');const name=document.createElement('strong');name.textContent=j.name;const info=document.createElement('small');info.textContent=(j.files||[]).map(e=>e.slice(1).toUpperCase()).join(' + ')+' · '+({ready:'к обработке',running:'обработка',done:'готово',error:'ошибка'}[j.state]||j.state);button.append(name,info);button.onclick=()=>selectJob(j);$('jobs').append(button)}
}
async function loadProjects(){
 const list=await api('/api/projects');const selected=$('projectSelect').value||localStorage.getItem('3d-project');
 $('projectSelect').replaceChildren();for(const p of list){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;$('projectSelect').append(o)}
 if(list.length){project=list.find(p=>p.id===selected)||list[0];$('projectSelect').value=project.id;localStorage.setItem('3d-project',project.id);renderMeasurements();renderPlan();mapIntegration?.update()}
 else{project=null;const o=document.createElement('option');o.textContent='Нет проектов';$('projectSelect').append(o)}
}
$('newProject').onclick=()=>{$('projectName').value='';$('projectDialog').showModal()};
$('createProject').onclick=async()=>{try{const p=await post('/api/projects',{name:$('projectName').value});$('projectDialog').close();localStorage.setItem('3d-project',p.id);$('projectSelect').value='';project=null;current=null;clearSceneModels();clearMeasurement();await loadProjects();await refresh()}catch(e){error(e.message)}};
$('projectSelect').onchange=async()=>{localStorage.setItem('3d-project',$('projectSelect').value);project=null;current=null;clearSceneModels();clearMeasurement();await loadProjects();await refresh()};
$('importCompact').onclick=$('importFileButton').onclick=()=>$('file').click();
$('planUpload').onclick=()=>$('planFile').click();
$('scanSelect').onchange=()=>{const job=jobs.find(j=>j.id===$('scanSelect').value);if(job)selectJob(job)};
$('file').onchange=async e=>{
 if(!project)return error('Сначала создай проект');const files=[...e.target.files];if(!files.length)return;
 const extensions=files.map(f=>f.name.split('.').at(-1).toLowerCase());if(files.length>2||new Set(extensions).size!==files.length||(files.length===2&&!(extensions.includes('las')&&extensions.includes('glb'))))return error('Выбирай один файл либо пару GLB + LAS одного скана');
 busyUpload=true;let id;error('');
 try{for(const file of files){$('status').textContent='Импортирую '+file.name;const headers={'X-Project-ID':project.id,'X-File-Name':encodeURIComponent(file.name)};if(id)headers['X-Scan-ID']=id;const r=await api('/api/upload',{method:'POST',headers,body:file});id=r.id}await refresh();const job=jobs.find(j=>j.id===id);if(job)await selectJob(job)}catch(e){error(e.message)}finally{busyUpload=false;$('file').value=''}
};
async function runProcessing(){if(!current)return error('Выбери скан');try{await post('/api/process',{id:current.id});await refresh()}catch(e){error(e.message)}}
$('process').onclick=runProcessing;$('processCompact').onclick=runProcessing;
$('viewMode').onchange=()=>show($('viewMode').value);$('fit').onclick=()=>fit();$('top').onclick=()=>fit(true);$('wire').onchange=wire;
const focusButton=document.createElement('button');focusButton.textContent='Развернуть вид';focusButton.id='focusView';focusButton.onclick=()=>{document.body.classList.toggle('sceneFocus');focusButton.textContent=document.body.classList.contains('sceneFocus')?'Вернуть панели':'Развернуть вид'};document.querySelector('.toolbar').append(focusButton);
$('cut').onchange=()=>{renderer.clippingPlanes=$('cut').checked?[new THREE.Plane(new THREE.Vector3(0,-1,0),2.4)]:[]};
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));for(const id of ['measurePanel','planPanel','qualityPanel','mapPanel'])$(id).hidden=id!==button.dataset.tab});
function renderPlan(){
 const p=project?.plan;const done=p?.state==='done';$('planStatus').textContent=!p?'Планировка не загружена':p.state==='running'?'Анализирую локально…':p.state==='error'?'Ошибка: '+p.error:`Найдено ${p.analysis.segmentsPixels.length} сегментов. Масштаб: ${p.analysis.metersPerPixel?.toFixed(5)||'не определён'} м/пиксель · требует проверки.`;
 $('planPreview').hidden=!done;$('planModel').disabled=!done||!p.analysis.model;$('planReport').hidden=!done;
 if(done){$('planPreview').src=`/data/projects/${project.id}/plan-analysis.png`;$('planReport').href=`/data/projects/${project.id}/plan-analysis.json`}
 $('planDimensions').replaceChildren();for(const d of p?.analysis?.recognizedDimensions||[]){const span=document.createElement('span');span.className='chip';span.textContent=d.valueMeters.toFixed(2)+' м';$('planDimensions').append(span)}
}
$('planFile').onchange=async e=>{if(!project)return error('Сначала создай проект');const file=e.target.files[0];if(!file)return;try{await api('/api/plan',{method:'POST',headers:{'X-Project-ID':project.id,'X-File-Name':encodeURIComponent(file.name)},body:file});await loadProjects()}catch(e){error(e.message)}$('planFile').value=''};
$('planModel').onclick=async()=>{try{const gltf=await new GLTFLoader().loadAsync(`/data/projects/${project.id}/plan-model.glb`);for(const root of cache.values())root.visible=false;const key='plan/'+project.id;if(cache.has(key)){scene.remove(cache.get(key));dispose(cache.get(key))}cache.set(key,gltf.scene);scene.add(gltf.scene);model=gltf.scene;before=after=null;mode='plan';$('variant').textContent='Модель плана · масштаб OCR, условные стены';for(const id of ['compareLine','compareControl','beforeLabel','afterLabel','heatLegend'])$(id).hidden=true;fit();$('tool').value='navigate';clearMeasurement()}catch(e){error(e.message)}};
function clearMeasurement(){for(const o of [...marks.children]){marks.remove(o);dispose(o)}picked=[];selection=null;measurement=null;$('measurementResult').textContent='Измерение не выбрано'}
function dot(p){const m=new THREE.Mesh(new THREE.SphereGeometry(.02,10,10),new THREE.MeshBasicMaterial({color:0xffd477,depthTest:false}));m.position.fromArray(p);marks.add(m)}
function line(points,close=false){const data=points.map(p=>new THREE.Vector3(...p));if(close&&data.length)data.push(data[0].clone());marks.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(data),new THREE.LineBasicMaterial({color:0xffd477,depthTest:false})))}
function hitAt(x,y){if(!model)return null;const r=renderer.domElement.getBoundingClientRect();pointer.set((x-r.left)/r.width*2-1,-(y-r.top)/r.height*2+1);ray.firstHitOnly=!$('cut').checked;ray.setFromCamera(pointer,camera);const hits=ray.intersectObject(model,true);return hits.find(h=>!$('cut').checked||h.point.y<=2.4)||null}
function updateMeasurement(finish=false){
 const tool=$('tool').value;if(picked.length<2)return;
 let value=0;for(let i=1;i<picked.length;i++)value+=distance(picked[i-1],picked[i]);
 if(tool==='polygon'){value=polygonArea(picked);$('measurementResult').textContent=`Площадь проекции: ${value.toFixed(3)} м²\nТочек: ${picked.length}`}
 else{const d=picked.at(-1).map((v,i)=>v-picked[0][i]);$('measurementResult').textContent=`${value.toFixed(3)} м\nПо горизонтали: ${Math.hypot(d[0],d[2]).toFixed(3)} м\nПо высоте: ${Math.abs(d[1]).toFixed(3)} м`}
 measurement={kind:tool,points:picked.map(p=>[...p]),value,units:tool==='polygon'?'m2':'m',source:mode,scan:current?.id,accuracyVerified:false};
 if(finish&&tool==='polygon')line(picked,true);
}
$('tool').onchange=()=>{clearMeasurement();const t=$('tool').value;controls.enabled=t!=='object';$('depthControl').hidden=t!=='object';$('toolHelp').textContent={navigate:'Левая кнопка — вращение, правая — перемещение, колесо — масштаб.',distance:'Нажми две точки поверхности. При сравнении измерение выполняется по исходной модели.',polyline:'Нажимай точки, затем «Завершить».',polygon:'Обведи контур точками. Площадь считается в горизонтальной проекции.',object:'Обведи объект рамкой. Выделяются видимые данные в заданной глубине; проверь подсветку и исключи фон.'}[t]};
$('clearMeasure').onclick=clearMeasurement;$('finishMeasure').onclick=()=>updateMeasurement(true);
renderer.domElement.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY};if($('tool').value==='object'){const r=renderer.domElement.getBoundingClientRect();$('selectionRect').hidden=false;Object.assign($('selectionRect').style,{left:(e.clientX-r.left)+'px',top:(e.clientY-r.top)+'px',width:'0px',height:'0px'});renderer.domElement.setPointerCapture(e.pointerId)}});
renderer.domElement.addEventListener('pointermove',e=>{if(!drag||$('tool').value!=='object')return;const r=renderer.domElement.getBoundingClientRect();Object.assign($('selectionRect').style,{left:(Math.min(drag.x,e.clientX)-r.left)+'px',top:(Math.min(drag.y,e.clientY)-r.top)+'px',width:Math.abs(e.clientX-drag.x)+'px',height:Math.abs(e.clientY-drag.y)+'px'})});
renderer.domElement.addEventListener('pointerup',e=>{
 if(!drag)return;const start=drag;drag=null;const t=$('tool').value;
 if(t==='object'){$('selectionRect').hidden=true;selection={x0:Math.min(start.x,e.clientX),y0:Math.min(start.y,e.clientY),x1:Math.max(start.x,e.clientX),y1:Math.max(start.y,e.clientY)};selectObject();return}
 if(t==='navigate'||Math.hypot(e.clientX-start.x,e.clientY-start.y)>5)return;
 if(t==='distance'&&picked.length===2)clearMeasurement();const hit=hitAt(e.clientX,e.clientY);if(!hit)return;
 const p=hit.object.isPoints?new THREE.Vector3().fromBufferAttribute(hit.object.geometry.attributes.position,hit.index).applyMatrix4(hit.object.matrixWorld):hit.point;
 picked.push(p.toArray());dot(p.toArray());if(picked.length>1)line(picked.slice(-2));updateMeasurement();
});
function selectObject(){
 if(!selection||!model)return;const rect={...selection};clearMeasurement();selection=rect;
 if(rect.x1-rect.x0<5||rect.y1-rect.y0<5)return;
 const sample=[];for(let y=0;y<8;y++)for(let x=0;x<8;x++){const h=hitAt(rect.x0+(x+.5)/8*(rect.x1-rect.x0),rect.y0+(y+.5)/8*(rect.y1-rect.y0));if(h)sample.push(h.distance)}
 if(!sample.length)return error('В рамке нет видимой поверхности');sample.sort((a,b)=>a-b);const near=sample[Math.floor(sample.length*.15)]-.04,depth=Number($('selectionDepth').value);if(!Number.isFinite(depth)||depth<.02||depth>5)return error('Глубина выделения: 0,02–5 м');
 const points=[],viewport=renderer.domElement.getBoundingClientRect();model.updateMatrixWorld(true);
 model.traverse(o=>{if(!o.geometry?.attributes.position)return;const positions=o.geometry.attributes.position;for(let i=0;i<positions.count;i++){vector.fromBufferAttribute(positions,i).applyMatrix4(o.matrixWorld);if($('cut').checked&&vector.y>2.4)continue;const d=vector.distanceTo(camera.position);if(d<near||d>near+depth)continue;const world=vector.toArray();vector.project(camera);if(vector.z<-1||vector.z>1)continue;const x=viewport.left+(vector.x+1)/2*viewport.width,y=viewport.top+(1-vector.y)/2*viewport.height;if(x>=rect.x0&&x<=rect.x1&&y>=rect.y0&&y<=rect.y1)points.push(world)}});
 if(points.length<3)return error('Слишком мало точек. Увеличь рамку или глубину');
 const result=dimensions(points),[a,b,h]=result.size;
 $('measurementResult').textContent=`Габариты выделения\nA: ${a.toFixed(3)} м · B: ${b.toFixed(3)} м\nВысота: ${h.toFixed(3)} м\nВершин: ${points.length.toLocaleString('ru')}\nПроверь, что фон не попал в выделение.`;
 const shown=points.filter((_,i)=>i%Math.max(1,Math.ceil(points.length/6000))===0);marks.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints(shown.map(p=>new THREE.Vector3(...p))),new THREE.PointsMaterial({color:0xffd477,size:.01,depthTest:false})));
 const corners=[];for(let z=0;z<2;z++)for(let y=0;y<2;y++)for(let x=0;x<2;x++){const values=[x?result.high[0]:result.low[0],y?result.high[1]:result.low[1],z?result.high[2]:result.low[2]];corners.push(result.center.map((v,i)=>v+values.reduce((s,t,j)=>s+t*result.axes[j][i],0)))}
 for(const [i,j] of [[0,1],[0,2],[1,3],[2,3],[4,5],[4,6],[5,7],[6,7],[0,4],[1,5],[2,6],[3,7]])line([corners[i],corners[j]]);
 measurement={kind:'object',dimensions:result,source:mode,scan:current?.id,accuracyVerified:false,depthMeters:depth};
}
$('selectionDepth').onchange=selectObject;
function renderMeasurements(){$('measurements').replaceChildren();for(const m of project?.measurements||[]){const item=document.createElement('div');item.className='measurement';const title=document.createElement('strong');title.textContent=m.name;const text=document.createElement('small');text.textContent=m.kind==='object'?m.dimensions.size.map(v=>v.toFixed(3)).join(' × ')+' м':m.value.toFixed(3)+(m.units==='m2'?' м²':' м');item.append(title,text);$('measurements').append(item)}}
$('saveMeasure').onclick=async()=>{if(!measurement||!project)return error('Сначала выполни измерение');try{const item={...measurement,id:crypto.randomUUID(),name:$('measurementName').value.trim()||'Измерение '+((project.measurements?.length||0)+1)};const items=[...(project.measurements||[]),item];await post('/api/measurements',{project:project.id,items});project.measurements=items;renderMeasurements();$('saved').textContent='Измерение сохранено';error('')}catch(e){error(e.message)}};
function downloadJSON(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('exportMeasures').onclick=()=>project&&downloadJSON('measurements.json',{project:project.name,units:'meters',accuracyVerified:false,measurements:project.measurements||[]});
async function refresh(){
 try{
  if(!project)return;const old=current;const loaded=await api(`/api/jobs?project=${project.id}`);jobs=loaded;renderJobs();
  const running=jobs.find(j=>j.state==='running');$('progress').hidden=!running;$('progress').value=running?.progress||0;
  if(!busyUpload)$('status').textContent=running?.message||current?.message||'Выбери скан или импортируй файлы';
  if(current){const updated=jobs.find(j=>j.id===current.id);if(updated){current=updated;updateInspector();if(old.state==='running'&&updated.state==='done'){for(const [key,root]of [...cache]){if(key.includes('straightened')||key.includes('points')||key.endsWith('/difference')){scene.remove(root);dispose(root);cache.delete(key)}}await show(updated.report.mesh?'compare':'points')}}}
  else if(jobs.length){const preferred=jobs.findLast(j=>(j.report?.points||0)>1000)||jobs.at(-1);await selectJob(preferred)}
  if(project.plan?.state==='running')await loadProjects();
 }catch(e){error(e.message)}
}
const mapIntegration=initMap({getProject:()=>project,getPoints:()=>picked,getCloud:async()=>{if(!current?.report.mesh)return [];const root=await getModel('mesh.glb'),points=[];root.updateMatrixWorld(true);root.traverse(o=>{const p=o.geometry?.attributes.position;if(!p)return;for(let i=0;i<p.count;i+=Math.max(1,Math.ceil(p.count/6000))){vector.fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);if(vector.y>.1&&vector.y<2.4)points.push(vector.toArray())}});return points},reloadProjects:loadProjects});
try{await loadProjects();await refresh()}catch(e){error(e.message)}
setInterval(refresh,1800);
