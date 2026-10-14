import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {computeBoundsTree,disposeBoundsTree,acceleratedRaycast} from './vendor/three-mesh-bvh.js';
import {dimensions,distance,polygonArea,surfaceArea} from './measurements.js';
import {withoutWallFaces,architecturalWalls} from './walls.js';
import {freeCamera} from './free-camera.js';
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
let cutLevel=2.4,hiddenWallIds=new Set();
const ray=new THREE.Raycaster();ray.firstHitOnly=true;ray.params.Points.threshold=.02;
const vector=new THREE.Vector3(),pointer=new THREE.Vector2();
function error(text){$('error').textContent=text;$('error').hidden=!text}
async function api(path,options={}){const r=await fetch(path,options),d=await r.json();if(!r.ok)throw new Error(d.error||'Ошибка сервера');return d}
const post=(path,data)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function dispose(root){root.traverse(o=>{if(o.userData.photoMaterial){o.material=o.userData.photoMaterial;o.userData.flatMaterial?.dispose()}});root.traverse(o=>{o.geometry?.disposeBoundsTree?.();o.geometry?.dispose();const materials=o.material?(Array.isArray(o.material)?o.material:[o.material]):[];for(const m of materials){m.map?.dispose();m.dispose()}})}
function clearSceneModels(){if(flight.active)flight.set(false);error('');++request;for(const root of cache.values()){scene.remove(root);dispose(root)}cache.clear();model=before=after=null;$('empty').hidden=false;$('variant').textContent='Выбери или импортируй скан';$('modelStats').textContent='Метры · Y вверх';$('mapStage').hidden=true;$('floorplanStage').hidden=true;for(const id of ['compareLine','compareControl','beforeLabel','afterLabel','heatLegend'])$(id).hidden=true;$('variant').dataset.ready='';updateInspector()}
new ResizeObserver(()=>{const w=$('viewport').clientWidth,h=$('viewport').clientHeight;if(!w||!h)return;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix()}).observe($('viewport'));
const flight=freeCamera(THREE,camera,controls,renderer.domElement,(active,position)=>{$('cameraMode').value=active?'free':'orbit';$('flightHelp').hidden=!active;if($('tool').value==='navigate')$('toolHelp').textContent=active?'WASD — движение, Q/E — вниз/вверх, Shift — быстрее, правая кнопка + мышь — осмотр. Esc — обычная камера.':'Левая кнопка — вращение, правая — перемещение, колесо — масштаб.';if(position)$('cameraPosition').textContent=`Камера: ${position.x.toFixed(2)} · ${position.y.toFixed(2)} · ${position.z.toFixed(2)} м`;});
let frameTime=performance.now();
renderer.setAnimationLoop(time=>{
 const dt=(time-frameTime)/1000;frameTime=time;if(flight.active)flight.update(dt);else controls.update();const w=$('viewport').clientWidth,h=$('viewport').clientHeight;
 if(['compare','compareForced'].includes(mode)&&before&&after){
  const split=Math.round(w*Number($('compareSlider').value)/100);renderer.setScissorTest(true);
  before.visible=true;after.visible=false;renderer.setScissor(0,0,split,h);renderer.render(scene,camera);
  before.visible=false;after.visible=true;renderer.setScissor(split,0,w-split,h);renderer.render(scene,camera);renderer.setScissorTest(false);
  $('compareLine').style.left=split+'px';before.visible=true;
 }else renderer.render(scene,camera);
});
function fit(top=false){if(!model)return;if(flight.active)flight.set(false);const box=new THREE.Box3().setFromObject(model),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());controls.target.copy(center);camera.up.set(0,top?0:1,top?-1:0);const v=THREE.MathUtils.degToRad(camera.fov),h=2*Math.atan(Math.tan(v/2)*camera.aspect);const d=Math.max(size.length()/2,1)/Math.sin(Math.min(v,h)/2)*1.06;camera.position.copy(center).addScaledVector(top?new THREE.Vector3(0,1,.00001):new THREE.Vector3(1,.7,1).normalize(),d);camera.far=Math.max(100,d*10);camera.updateProjectionMatrix();controls.update();grid.position.y=box.min.y-.02}
async function getModel(file){
 const job=current,key=job.id+'/'+file;if(cache.has(key))return cache.get(key);
 const gltf=await new GLTFLoader().loadAsync(`/data/${key}?v=${job.report.processingVersion||0}`);
 if(current?.id!==job.id){dispose(gltf.scene);throw new Error('Выбран другой скан')}
 if(cache.has(key)){dispose(gltf.scene);return cache.get(key)}
 // Keep full-resolution source files; reduce only GPU preview textures.
 const previewTextures=new Set();gltf.scene.traverse(o=>{for(const material of (o.material?(Array.isArray(o.material)?o.material:[o.material]):[]))for(const value of Object.values(material))if(value?.isTexture&&value.image)previewTextures.add(value)});
 const resized=new Map(),previewLimit=Math.min(4096,renderer.capabilities.maxTextureSize);
 for(const texture of previewTextures){const img=texture.image;if(Math.max(img.width,img.height)<=previewLimit)continue;if(!resized.has(img)){const factor=previewLimit/Math.max(img.width,img.height);resized.set(img,await createImageBitmap(img,{resizeWidth:Math.round(img.width*factor),resizeHeight:Math.round(img.height*factor),resizeQuality:'high'}))}texture.image=resized.get(img);texture.needsUpdate=true}
 for(const img of resized.keys())img.close?.();if(current?.id!==job.id){dispose(gltf.scene);throw new Error('Выбран другой скан')}
 if(job.report.availableFiles?.includes('planes.json')&&!job.wallPlanes)job.wallPlanes=(await api(`/data/${job.id}/planes.json`)).planes;
 gltf.scene.traverse(o=>{if(o.isMesh){o.userData.wallPlanes=job.wallPlanes||[];o.geometry.computeBoundsTree();for(const material of (Array.isArray(o.material)?o.material:[o.material])){material.side=THREE.DoubleSide;const definition=gltf.parser.json.materials?.[gltf.parser.associations.get(material)?.materials]?.pbrMetallicRoughness;if(material.map&&definition&&definition.metallicFactor===undefined&&!definition.metallicRoughnessTexture){material.metalness=0;material.needsUpdate=true}}}if(o.isPoints){o.material.size=.012;o.material.sizeAttenuation=true}});
 gltf.scene.visible=false;scene.add(gltf.scene);cache.set(key,gltf.scene);return gltf.scene;
}
function meshParts(root){const parts=[];root.traverse(o=>{if(o.isMesh)parts.push(o)});return parts}
async function differenceModel(){
 const key=current.id+'/difference';if(cache.has(key))return cache.get(key);
 const source=meshParts(await getModel('mesh.glb')),processed=meshParts(await getModel('straightened.glb'));
 if(!source.length||source.length!==processed.length)throw new Error('Сетки несовместимы для карты изменений');
 const result=new THREE.Group();
 for(let part=0;part<source.length;part++){
  const a=source[part],b=processed[part],p=a.geometry.attributes.position,q=b.geometry.attributes.position;
  if(p.count!==q.count)throw new Error('Части сетки несовместимы');
  const geometry=b.geometry.clone(),colors=new Float32Array(p.count*3),color=new THREE.Color();
  for(let i=0;i<p.count;i++){const t=Math.min(1,Math.hypot(p.getX(i)-q.getX(i),p.getY(i)-q.getY(i),p.getZ(i)-q.getZ(i))/.005);color.set(t<.02?0x53616d:t<.5?0x39b88c:0xe3ba51);if(t>.85)color.set(0xe36450);color.toArray(colors,i*3)}
  geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));geometry.computeBoundsTree();
  const mesh=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.DoubleSide}));b.updateWorldMatrix(true,false);mesh.matrix.copy(b.matrixWorld);mesh.matrixAutoUpdate=false;mesh.userData.wallPlanes=b.userData.wallPlanes;mesh.userData.originalIndex=b.userData.originalIndex?.clone();result.add(mesh);
 }
 result.visible=false;scene.add(result);cache.set(key,result);return result;
}
async function show(nextMode='mesh',reset=false){
 if(!current?.report||(!current.report.mesh&&!current.report.pointCloud))return;
 const ticket=++request;error('');$('empty').hidden=true;$('variant').textContent='Загружается модель…';$('variant').dataset.ready='loading';
 try{
  let target,original,processed;
  if(['forced','compareForced'].includes(nextMode)&&!current.report.forced)throw new Error('Включи галочку принудительного выравнивания и нажми «Обработать»');
  if(['corrected','compare','difference'].includes(nextMode)&&(!current.report.straightened||current.report.processingVersion!==2))throw new Error('Сначала выполни обработку v2');
  if(nextMode==='points'&&!current.report.pointCloud)throw new Error('Облако LAS ещё не обработано');
  if(nextMode==='old'&&!current.report.legacyResult)throw new Error('Архивная обработка v1 отсутствует');
  if(['compare','compareForced'].includes(nextMode)){original=await getModel('mesh.glb');processed=await getModel(nextMode==='compareForced'?'forced.glb':'straightened.glb');target=original}
  else if(nextMode==='difference')target=await differenceModel();
  else target=await getModel(nextMode==='forced'?'forced.glb':nextMode==='corrected'?'straightened.glb':nextMode==='points'||!current.report.mesh?'points.glb':nextMode==='old'?'previous-v1.glb':'mesh.glb');
  if(ticket!==request)return;
  for(const root of cache.values())root.visible=false;
  model=target;model.visible=true;before=original;after=processed;mode=nextMode;
  $('viewMode').value=mode;$('mapStage').hidden=true;$('floorplanStage').hidden=true;$('empty').hidden=true;
  for(const id of ['compareLine','compareControl','beforeLabel','afterLabel'])$(id).hidden=!['compare','compareForced'].includes(mode);
  $('heatLegend').hidden=mode!=='difference';
  $('variant').textContent={forced:'Проекция архитектуры на плоскости · размеры требуют проверки',compareForced:'Исходный / принудительно выровненный',mesh:'Исходная модель',corrected:'Обработка v2 · ограниченные правки',compare:'Один ракурс · два результата',difference:'Сдвиг вершин относительно исходного GLB',points:'Облако точек LAS',old:'Архив v1 · содержит дефекты'}[mode];
  $('variant').dataset.ready=mode;$('afterLabel').textContent=mode==='compareForced'?'Выравнивание плоскостей':'Обработка v2';
  if(reset)fit();applyAppearance();wire();applyCut();applyWalls();renderWallControls();updateInspector();$('hideWalls').disabled=mode==='points'||mode==='plan';
 }catch(e){if(ticket!==request)return;error(e.message);$('viewMode').value=mode;$('variant').textContent='Ошибка загрузки: '+e.message;$('variant').dataset.ready='error'}
}
function applyAppearance(){for(const root of cache.values())root.traverse(o=>{if(!o.isMesh)return;if(!o.userData.photoMaterial&&(Array.isArray(o.material)?o.material:[o.material]).some(m=>m.map)){o.userData.photoMaterial=o.material;o.userData.flatMaterial=new THREE.MeshStandardMaterial({color:0xb9c3cb,roughness:1,metalness:0,flatShading:!o.geometry.attributes.normal,side:THREE.DoubleSide})}if(o.userData.photoMaterial)o.material=$('solidView').checked?o.userData.flatMaterial:o.userData.photoMaterial});wire()}
$('solidView').onchange=applyAppearance;
$('cameraMode').onchange=()=>{if(!model){$('cameraMode').value='orbit';return}if($('cameraMode').value==='free'){if(['map','floorplan','plan'].includes(mode)){error('Сначала выбери 3D-модель или облако точек');$('cameraMode').value='orbit';return}const box=new THREE.Box3().setFromObject(model),center=box.getCenter(new THREE.Vector3());let floor=box.min.y;let planes=current?.wallPlanes||[];if(!planes.length)model.traverse(o=>{if(o.userData.wallPlanes?.length)planes=o.userData.wallPlanes});const largest=Math.max(0,...planes.filter(p=>p.kind==='horizontal').map(p=>p.areaM2));const horizontal=planes.filter(p=>p.kind==='horizontal'&&p.areaM2>=Math.max(2,largest*.15));if(horizontal.length)floor=Math.min(...horizontal.map(p=>-p.constant/p.normal[1]));camera.position.set(center.x,floor+1.6,center.z);camera.up.set(0,1,0);camera.lookAt(center.x,floor+1.6,box.min.z);$('tool').value='navigate';configureTool();flight.set(true)}else flight.set(false)};
function wire(){for(const root of cache.values())root.traverse(o=>{if(o.isMesh)for(const m of (Array.isArray(o.material)?o.material:[o.material]))m.wireframe=$('wire').checked})}
function updateInspector(){
 const r=current?.report||{},c=r.planarAnalysis?.changes;$('fit').disabled=$('top').disabled=!model;
 $('modelStats').textContent=mode==='plan'?'Черновая модель плана · условный масштаб':current?`${current.name} · метры`: 'Метры · Y вверх';
 const fc=r.forcedAnalysis?.changes;$('forcedChanges').textContent=fc?`${fc.processedPlanes} плоскостей · ${fc.movedVertices.toLocaleString('ru')} вершин\nМаксимальный сдвиг: ${fc.maximumShiftMm.toFixed(1)} мм\nИзменение габаритов X/Y/Z: ${fc.extentChangeMm.map(v=>v.toFixed(1)).join(' / ')} мм\nОтброшено при риске переворота: ${fc.rejectedFoldFaces} граней\nРеальная точность не подтверждена`:'Отдельная модель ещё не создана. Нажми «Применить принудительное выравнивание».';
 $('changes').textContent=c?`${c.movedVertices.toLocaleString('ru')} вершин изменены\nМаксимальный сдвиг: ${c.maximumShiftMm.toFixed(2)} мм\nПредельный наклон: ${(c.maximumNormalChangeDegrees||0).toFixed(2)}°\nСогласованных швов: ${c.weldedSeamGroups||0}\nGPU: ${r.planarAnalysis.backend||'CPU'}`:'Обработка v2 ещё не выполнена';
 const align=r.las?.alignment;$('alignment').textContent=align?`Медиана расстояния облака до вершин сетки: ${align.medianDistanceMm.toFixed(1)} мм. Это согласование двух экспортов, а не точность относительно реального объекта.`:r.pointCloud?(r.las?'LAS без пары GLB: локальные координаты, Y вверх.':'Облако точек импортировано из GLB.'):'Данные совмещения отсутствуют';
 $('exports').replaceChildren();
 for(const name of (r.availableFiles||[]).filter(n=>n.endsWith('.glb')||n.endsWith('.ply'))){const a=document.createElement('a');a.textContent=name.replace('.glb','').replace('.ply',' PLY');a.href=`/data/${current.id}/${name}`;a.download=name;$('exports').append(a)}
 $('plan').hidden=!r.planComparison;if(r.planComparison)$('plan').href=`/data/${current.id}/${r.planComparison}`;
 const available={forced:!!r.forced,compareForced:!!r.forced,mesh:!!r.mesh,points:!!r.pointCloud,corrected:!!r.straightened&&r.processingVersion===2,compare:!!r.straightened&&r.processingVersion===2,difference:!!r.straightened&&r.processingVersion===2,old:!!r.legacyResult,map:!!project?.mpunav,floorplan:!!project?.floorplan&&project.floorplan.scan===current?.id&&!project.floorplan.stale&&Math.abs(project.floorplan.factor-metricFactor())<1e-8};for(const option of $('viewMode').options)option.disabled=!available[option.value];
 $('process').disabled=busyUpload||!current||jobs.some(j=>j.state==='running');$('processCompact').disabled=$('process').disabled;$('forceApply').disabled=$('process').disabled;$('forcePlanes').disabled=busyUpload||jobs.some(j=>j.state==='running');
}
async function selectJob(job){const same=current?.id===job.id;if(!same){++request;clearSceneModels();clearMeasurement();$('measurementName').value='';$('calibrationReal').value='';$('calibrationName').value='';try{hiddenWallIds=new Set(JSON.parse(localStorage.getItem('3d-hidden-walls-'+job.id)||'[]'))}catch{hiddenWallIds=new Set()}}current=job;$('forcePlanes').checked=!!job.forcePlanes;renderJobs();updateInspector();renderFloorplan();renderCalibration();await show(job.report.mesh?'mesh':job.report.pointCloud?'points':'mesh',!same)}
function renderJobs(){
 $('scanSelect').replaceChildren();for(const j of jobs){const option=document.createElement('option');option.value=j.id;option.textContent=j.name;$('scanSelect').append(option)}if(current)$('scanSelect').value=current.id;
 $('jobs').replaceChildren();for(const j of jobs){const button=document.createElement('button');button.className='job'+(j.id===current?.id?' selected':'');const name=document.createElement('strong');name.textContent=j.name;const info=document.createElement('small');info.textContent=(j.files||[]).map(e=>e.slice(1).toUpperCase()).join(' + ')+' · '+({ready:'к обработке',running:'обработка',done:'готово',error:'ошибка'}[j.state]||j.state);button.append(name,info);button.onclick=()=>selectJob(j);$('jobs').append(button)}
}
async function loadProjects(){
 const list=await api('/api/projects');const selected=$('projectSelect').value||localStorage.getItem('3d-project');
 $('projectSelect').replaceChildren();for(const p of list){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;$('projectSelect').append(o)}
 if(list.length){project=list.find(p=>p.id===selected)||list[0];$('projectSelect').value=project.id;localStorage.setItem('3d-project',project.id);renderMeasurements();renderPlan();renderFloorplan();renderCalibration();mapIntegration?.update()}
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
 const extensions=files.map(f=>f.name.split('.').at(-1).toLowerCase());if(files.length>2||new Set(extensions).size!==files.length||(files.length===2&&!((extensions.includes('las')||extensions.includes('laz'))&&extensions.includes('glb')))){e.target.value='';return error('Выбирай один файл либо пару GLB + LAS/LAZ одного скана')}
 busyUpload=true;let id;error('');for(const key of ['projectSelect','newProject','importCompact','importFileButton'])$(key).disabled=true;updateInspector();
 try{for(const file of files){$('status').textContent='Импортирую '+file.name;$('sceneStatus').textContent=$('status').textContent;$('sceneStatus').hidden=false;const headers={'X-Project-ID':project.id,'X-File-Name':encodeURIComponent(file.name)};if(id)headers['X-Scan-ID']=id;const r=await api('/api/upload',{method:'POST',headers,body:file});id=r.id}await refresh();const job=jobs.find(j=>j.id===id);if(job)await selectJob(job)}catch(e){error(e.message)}finally{busyUpload=false;for(const key of ['projectSelect','newProject','importCompact','importFileButton'])$(key).disabled=false;$('file').value='';updateInspector()}
};
async function runProcessing(){if(!current)return error('Выбери скан');try{await post('/api/process',{id:current.id,forcePlanes:$('forcePlanes').checked});await refresh()}catch(e){error(e.message)}}
$('forceApply').onclick=()=>{$('forcePlanes').checked=true;runProcessing()};$('process').onclick=runProcessing;$('processCompact').onclick=runProcessing;
$('viewMode').onchange=()=>{clearMeasurement();if($('viewMode').value==='floorplan')openFloorplan();else if($('viewMode').value==='map')$('mapOpen').click();else show($('viewMode').value)};$('fit').onclick=()=>fit();$('top').onclick=()=>fit(true);$('wire').onchange=wire;
const focusButton=document.createElement('button');focusButton.textContent='Развернуть вид';focusButton.id='focusView';focusButton.onclick=()=>{document.body.classList.toggle('sceneFocus');focusButton.textContent=document.body.classList.contains('sceneFocus')?'Вернуть панели':'Развернуть вид'};document.querySelector('.toolbar').append(focusButton);
function applyCut(){if(model){const box=new THREE.Box3().setFromObject(model),height=box.max.y-box.min.y;cutLevel=height>1.8?box.min.y+height*.92:box.max.y+1}let planes=current?.wallPlanes||[];if(!planes.length&&model)model.traverse(o=>{if(o.userData.wallPlanes?.length)planes=o.userData.wallPlanes});const horizontal=planes.filter(p=>p.kind==='horizontal'),largest=Math.max(0,...horizontal.map(p=>p.areaM2)),heights=horizontal.filter(p=>p.areaM2>=largest*.15).map(p=>-p.constant/p.normal[1]);if(heights.length>1){const floor=Math.min(...heights),ceiling=heights.filter(y=>y-floor>1.8);if(ceiling.length)cutLevel=Math.min(...ceiling)-.05}renderer.clippingPlanes=$('cut').checked?[new THREE.Plane(new THREE.Vector3(0,-1,0),cutLevel)]:[]}
$('cut').onchange=applyCut;
function applyWalls(){
 for(const root of cache.values())root.traverse(o=>{
  if(!o.isMesh||!o.userData.wallPlanes?.length)return;
  const g=o.geometry;
  if(!o.userData.originalIndex)o.userData.originalIndex=g.index?.clone()||new THREE.BufferAttribute(Uint32Array.from({length:g.attributes.position.count},(_,i)=>i),1);
  const signature=[...hiddenWallIds].sort((a,b)=>a-b).join(',');if(hiddenWallIds.size&&o.userData.wallSignature!==signature){
   root.updateMatrixWorld(true);const p=g.attributes.position,world=new Float32Array(p.count*3);for(let i=0;i<p.count;i++){vector.fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);vector.toArray(world,i*3)}
   const kept=withoutWallFaces(world,o.userData.originalIndex.array,o.userData.wallPlanes,hiddenWallIds);o.userData.wallFreeIndex=new THREE.BufferAttribute(kept,1);o.userData.visibleVertices=new Set(kept);o.userData.wallSignature=signature;
  }
  const next=hiddenWallIds.size?o.userData.wallFreeIndex:o.userData.originalIndex;
  if(g.index!==next){g.disposeBoundsTree();g.setIndex(next);g.computeBoundsTree()}
 });
}
function availableWalls(){let found=[];model?.traverse(o=>{if(o.userData.wallPlanes?.length)found=architecturalWalls(o.userData.wallPlanes)});return found}
function renderWallControls(){const walls=availableWalls();$('wallChoices').replaceChildren();$('hideWalls').checked=walls.length>0&&walls.every(p=>hiddenWallIds.has(p.id));$('hideWalls').indeterminate=walls.some(p=>hiddenWallIds.has(p.id))&&!$('hideWalls').checked;for(const wall of walls){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=!hiddenWallIds.has(wall.id);input.dataset.wall=wall.id;const ends=wall.segmentXZ,length=ends?Math.hypot(ends[1][0]-ends[0][0],ends[1][1]-ends[0][1])*metricFactor():0;label.append(input,`Стена ${wall.id+1} · ${length.toFixed(2)} м`);input.onchange=()=>{if(input.checked)hiddenWallIds.delete(wall.id);else hiddenWallIds.add(wall.id);saveWallView()};$('wallChoices').append(label)}if(!walls.length)$('wallChoices').textContent='Обработай GLB для распознавания стен.'}
function saveWallView(){if(current)localStorage.setItem('3d-hidden-walls-'+current.id,JSON.stringify([...hiddenWallIds]));applyWalls();renderWallControls()}
$('hideWalls').onchange=()=>{hiddenWallIds=$('hideWalls').checked?new Set(availableWalls().map(p=>p.id)):new Set();saveWallView()};
function renderFloorplan(){
 const f=project?.floorplan,valid=!!f&&!!current&&f.scan===current.id;const stale=valid&&(f.stale||Math.abs(f.factor-metricFactor())>1e-8);$('floorplanOpen').disabled=!valid||stale;$('floorplanBuild').disabled=!current?.report.mesh||current?.state==='running';
 if(valid){$('floorplanHeight').value=f.sectionMeters;$('floorplanScale').value=f.sheetScale}
 $('floorplanStatus').textContent=!valid?'План текущего скана ещё не построен':`${f.walls.length} плоскостей стен · ${f.walls.reduce((sum,w)=>sum+w.gaps.length,0)} разрывов для проверки\nНаблюдаемая площадь пола: ${f.observedFloorAreaM2?.toFixed(2)||'—'} м²\nКоэффициент: ${f.factor.toFixed(6)}${stale?' · данные изменены, перестрой план':''}`;
 $('floorplanExports').replaceChildren();$('floorplanGaps').replaceChildren();if(!valid||stale)return;
 for(const [file,label]of [['floorplan.svg','SVG · чертёж A3'],['floorplan.dxf','DXF · стены в миллиметрах'],['floorplan.csv','CSV · ведомость фрагментов'],['floorplan.json','JSON · геометрия и диагностика']]){const a=document.createElement('a');a.href=`/data/${f.scan}/${file}`;a.download=file;a.textContent=label;$('floorplanExports').append(a)}
 for(const wall of f.walls)for(const gap of wall.gaps){const p=document.createElement('p');p.className='hint';p.textContent=`Стена ${wall.id}: разрыв ${gap.widthMeters.toFixed(3)} м. Проём или пропуск — проверь на месте.`;$('floorplanGaps').append(p)}
}
function openFloorplan(){if(flight.active)flight.set(false);const f=project?.floorplan;if(!f||!current||f.scan!==current.id)return;if(f.stale||Math.abs(f.factor-metricFactor())>1e-8)return error('Данные или масштаб изменены. Перестрой план.');$('floorplanDrawing').src=`/data/${f.scan}/floorplan.svg?v=${Date.now()}`;$('floorplanStage').hidden=false;$('mapStage').hidden=true;mode='floorplan';$('viewMode').value='floorplan';for(const id of ['compareLine','compareControl','beforeLabel','afterLabel','heatLegend'])$(id).hidden=true;$('variant').textContent='Чертёж по скану · контрольные обмеры обязательны';$('variant').dataset.ready='floorplan'}
$('floorplanBuild').onclick=async()=>{const button=$('floorplanBuild');try{if(!current)throw new Error('Выбери скан');button.disabled=true;$('floorplanStatus').textContent='Строю сечение стен и размерные линии…';await post('/api/floorplan',{project:project.id,scan:current.id,sectionMeters:Number($('floorplanHeight').value),sheetScale:Number($('floorplanScale').value)});await loadProjects();openFloorplan();error('')}catch(e){error(e.message);$('floorplanStatus').textContent=e.message}finally{button.disabled=!current?.report.mesh}};
$('floorplanZoom').oninput=()=>{const paper=$('floorplanPaper'),image=$('floorplanDrawing'),old=Number(image.dataset.zoom||1),next=Number($('floorplanZoom').value)/100,cx=(paper.scrollLeft+paper.clientWidth/2)/old,cy=(paper.scrollTop+paper.clientHeight/2)/old;image.style.transform=`scale(${next})`;image.dataset.zoom=next;paper.scrollLeft=cx*next-paper.clientWidth/2;paper.scrollTop=cy*next-paper.clientHeight/2;$('floorplanZoomValue').textContent=$('floorplanZoom').value+'%'};
$('floorplanOpen').onclick=openFloorplan;$('floorplanClose').onclick=()=>show(current?.report.mesh?'mesh':'points');
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));for(const id of ['measurePanel','floorplanPanel','planPanel','qualityPanel','calibrationPanel','mapPanel'])$(id).hidden=id!==button.dataset.tab});
$('baselineExport').onclick=async()=>{try{await post('/api/baseline',{project:project.id,scan:current.id,export:true});await loadProjects()}catch(e){error(e.message)}};
$('baselineEnabled').onchange=async()=>{try{await post('/api/baseline',{project:project.id,enabled:$('baselineEnabled').checked});await loadProjects();updateMeasurement()}catch(e){error(e.message);renderCalibration()}};
function renderPlan(){
 const p=project?.plan;const done=p?.state==='done';$('planUpload').disabled=p?.state==='running';$('planStatus').textContent=!p?'Планировка не загружена':p.state==='running'?'Анализирую локально…':p.state==='error'?'Ошибка: '+p.error:`Найдено ${p.analysis.segmentsPixels.length} сегментов. Масштаб: ${p.analysis.metersPerPixel?.toFixed(5)||'не определён'} м/пиксель · требует проверки.`;
 $('planPreview').hidden=!done;$('planModel').disabled=!done||!p.analysis.model;$('planReport').hidden=!done;
 if(done){$('planPreview').src=`/data/projects/${project.id}/plan-analysis.png`;$('planReport').href=`/data/projects/${project.id}/plan-analysis.json`}
 $('planExports').replaceChildren();for(const file of project?.planExports||[]){const a=document.createElement('a');a.href=`/data/projects/${project.id}/${file.file}`;a.download=file.file;a.textContent=file.label;$('planExports').append(a)}$('polycamSummary').textContent=project?.polycamSummary?`План Polycam: ${project.polycamSummary.floorAreaM2} м² внутри, ${project.polycamSummary.exteriorAreaM2} м² снаружи; высота ${project.polycamSummary.ceilingHeight}. Значения Polycam, не независимая калибровка.`:'';
 $('planDimensions').replaceChildren();for(const d of p?.analysis?.recognizedDimensions||[]){const span=document.createElement('span');span.className='chip';span.textContent=d.valueMeters.toFixed(2)+' м';$('planDimensions').append(span)}
}
$('planFile').onchange=async e=>{if(!project)return error('Сначала создай проект');const file=e.target.files[0];if(!file)return;try{await api('/api/plan',{method:'POST',headers:{'X-Project-ID':project.id,'X-File-Name':encodeURIComponent(file.name)},body:file});await loadProjects()}catch(e){error(e.message)}$('planFile').value=''};
$('planModel').onclick=async()=>{try{const gltf=await new GLTFLoader().loadAsync(`/data/projects/${project.id}/plan-model.glb`);for(const root of cache.values())root.visible=false;const key='plan/'+project.id;if(cache.has(key)){scene.remove(cache.get(key));dispose(cache.get(key))}cache.set(key,gltf.scene);scene.add(gltf.scene);model=gltf.scene;before=after=null;mode='plan';$('mapStage').hidden=true;$('floorplanStage').hidden=true;$('variant').textContent='Модель плана · масштаб OCR, условные стены';for(const id of ['compareLine','compareControl','beforeLabel','afterLabel','heatLegend'])$(id).hidden=true;fit();$('tool').value='navigate';configureTool();$('viewMode').value='plan';$('variant').dataset.ready='plan';applyCut();updateInspector();$('empty').hidden=true}catch(e){error(e.message)}};
function clearMeasurement(){for(const o of [...marks.children]){marks.remove(o);dispose(o)}picked=[];selection=null;measurement=null;$('selectionRect').hidden=true;$('measurementResult').textContent='Измерение не выбрано'}
function dot(p){const m=new THREE.Mesh(new THREE.SphereGeometry(.02,10,10),new THREE.MeshBasicMaterial({color:0xffd477,depthTest:false}));m.position.fromArray(p);marks.add(m)}
function line(points,close=false){const data=points.map(p=>new THREE.Vector3(...p));if(close&&data.length)data.push(data[0].clone());marks.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(data),new THREE.LineBasicMaterial({color:0xffd477,depthTest:false})))}
function hitAt(x,y){if(!model)return null;const r=renderer.domElement.getBoundingClientRect();pointer.set((x-r.left)/r.width*2-1,-(y-r.top)/r.height*2+1);ray.firstHitOnly=!$('cut').checked;ray.setFromCamera(pointer,camera);const hits=ray.intersectObject(model,true);return hits.find(h=>!$('cut').checked||h.point.y<=cutLevel)||null}
function updateMeasurement(finish=false){
 const tool=$('tool').value;if(picked.length<(['polygon','surface'].includes(tool)?3:2)){measurement=null;if(['polygon','surface'].includes(tool))$('measurementResult').textContent='Для площади нужно минимум 3 точки';return}
 let value=0;for(let i=1;i<picked.length;i++)value+=distance(picked[i-1],picked[i]);
 const scale=metricFactor(),isArea=['polygon','surface'].includes(tool);if(tool==='surface'){const shape=surfaceArea(picked);value=shape.area*scale*scale;$('measurementResult').textContent=`Площадь поверхности: ${value.toFixed(3)} м²\nНеплоскостность контура: ${(shape.maximumPlaneDeviation*scale*1000).toFixed(1)} мм\nПроёмы вычитай отдельными замерами`}else if(tool==='polygon'){const rawArea=polygonArea(picked);value=rawArea*scale*scale;$('measurementResult').textContent=`Площадь проекции: ${value.toFixed(3)} м²\nТочек: ${picked.length}`}
 else{value*=scale;const d=picked.at(-1).map((v,i)=>v-picked[0][i]);$('measurementResult').textContent=`${value.toFixed(3)} м\nПо горизонтали: ${(Math.hypot(d[0],d[2])*scale).toFixed(3)} м\nПо высоте: ${(Math.abs(d[1])*scale).toFixed(3)} м`}
 if(isArea&&value<1e-8){measurement=null;$('measurementResult').textContent='Контур имеет нулевую площадь. Выбери точки по периметру.';return}
 measurement={kind:tool,points:picked.map(p=>[...p]),value,rawValue:value/(isArea?scale*scale:scale),calibrationFactor:scale,units:isArea?'m2':'m',source:mode,scan:current?.id,accuracyVerified:false};
 if(finish&&isArea){if(!measurement.closed)line(picked,true);measurement.closed=true}
}
function configureTool(){clearMeasurement();const t=$('tool').value;if(t!=='navigate'&&flight.active)flight.set(false);controls.enabled=!flight.active&&t!=='object';$('depthControl').hidden=t!=='object';$('toolHelp').textContent={navigate:'Левая кнопка — вращение, правая — перемещение, колесо — масштаб.',distance:'Нажми две точки поверхности. При сравнении измерение выполняется по исходной модели.',polyline:'Нажимай точки, затем «Завершить».',polygon:'Обведи контур точками. Площадь считается в горизонтальной проекции.',surface:'Обведи стену или поверхность точками по периметру, затем «Завершить». Это площадь контура; проёмы не вычитаются автоматически.',wall:'Нажми распознанную боковую стену. Вернуть её можно галочкой в «Стены в 3D».',object:'Обведи объект рамкой. Выделяются видимые данные в заданной глубине; проверь подсветку и исключи фон.'}[t]}
$('tool').onchange=configureTool;$('pickWall').onclick=()=>{$('tool').value='wall';configureTool();if(mode==='floorplan'||mode==='map')show('mesh')};
$('clearMeasure').onclick=clearMeasurement;$('finishMeasure').onclick=()=>updateMeasurement(true);
renderer.domElement.addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY};if($('tool').value==='object'){const r=renderer.domElement.getBoundingClientRect();$('selectionRect').hidden=false;Object.assign($('selectionRect').style,{left:(e.clientX-r.left)+'px',top:(e.clientY-r.top)+'px',width:'0px',height:'0px'});renderer.domElement.setPointerCapture(e.pointerId)}});
renderer.domElement.addEventListener('pointermove',e=>{if(!drag||$('tool').value!=='object')return;const r=renderer.domElement.getBoundingClientRect();Object.assign($('selectionRect').style,{left:(Math.min(drag.x,e.clientX)-r.left)+'px',top:(Math.min(drag.y,e.clientY)-r.top)+'px',width:Math.abs(e.clientX-drag.x)+'px',height:Math.abs(e.clientY-drag.y)+'px'})});
renderer.domElement.addEventListener('pointerup',e=>{
 if(!drag)return;const start=drag;drag=null;const t=$('tool').value;
 if(t==='object'){$('selectionRect').hidden=true;selection={x0:Math.min(start.x,e.clientX),y0:Math.min(start.y,e.clientY),x1:Math.max(start.x,e.clientX),y1:Math.max(start.y,e.clientY)};selectObject();return}
 if(t==='navigate'||Math.hypot(e.clientX-start.x,e.clientY-start.y)>5)return;
 if(t==='distance'&&picked.length===2)clearMeasurement();const hit=hitAt(e.clientX,e.clientY);if(!hit)return;
 const p=hit.object.isPoints?new THREE.Vector3().fromBufferAttribute(hit.object.geometry.attributes.position,hit.index).applyMatrix4(hit.object.matrixWorld):hit.point;
 if(t==='wall'){const normal=hit.face?.normal.clone().transformDirection(hit.object.matrixWorld),walls=availableWalls().filter(w=>normal&&Math.abs(normal.dot(new THREE.Vector3(...w.normal)))>.8).map(w=>({wall:w,d:Math.abs(p.dot(new THREE.Vector3(...w.normal))+w.constant)})).sort((a,b)=>a.d-b.d);if(!walls.length||walls[0].d>.07)return error('Нажми на распознанную стену, а не на пол или предмет');hiddenWallIds.add(walls[0].wall.id);saveWallView();$('toolHelp').textContent=`Стена ${walls[0].wall.id+1} скрыта. Вернуть её можно галочкой в «Стены в 3D».`;return}
 picked.push(p.toArray());dot(p.toArray());if(picked.length>1)line(picked.slice(-2));updateMeasurement();
});
function selectObject(){
 if(!selection||!model)return;const rect={...selection};clearMeasurement();selection=rect;
 if(rect.x1-rect.x0<5||rect.y1-rect.y0<5)return;
 const sample=[];for(let y=0;y<8;y++)for(let x=0;x<8;x++){const h=hitAt(rect.x0+(x+.5)/8*(rect.x1-rect.x0),rect.y0+(y+.5)/8*(rect.y1-rect.y0));if(h)sample.push(h.distance)}
 if(!sample.length)return error('В рамке нет видимой поверхности');sample.sort((a,b)=>a-b);const near=sample[Math.floor(sample.length*.15)]-.04,shownDepth=Number($('selectionDepth').value),depth=shownDepth/metricFactor();if(!Number.isFinite(shownDepth)||shownDepth<.02||shownDepth>5)return error('Глубина выделения: 0,02–5 м');
 const points=[],viewport=renderer.domElement.getBoundingClientRect();model.updateMatrixWorld(true);
 model.traverse(o=>{if(!o.geometry?.attributes.position)return;const positions=o.geometry.attributes.position;for(let i=0;i<positions.count;i++){vector.fromBufferAttribute(positions,i).applyMatrix4(o.matrixWorld);if($('cut').checked&&vector.y>cutLevel)continue;if(hiddenWallIds.size&&o.userData.visibleVertices&&!o.userData.visibleVertices.has(i))continue;const d=vector.distanceTo(camera.position);if(d<near||d>near+depth)continue;const world=vector.toArray();vector.project(camera);if(vector.z<-1||vector.z>1)continue;const x=viewport.left+(vector.x+1)/2*viewport.width,y=viewport.top+(1-vector.y)/2*viewport.height;if(x>=rect.x0&&x<=rect.x1&&y>=rect.y0&&y<=rect.y1)points.push(world)}});
 if(points.length<3)return error('Слишком мало точек. Увеличь рамку или глубину');
 const result=dimensions(points),scale=metricFactor(),[a,b,h]=result.size.map(v=>v*scale);
 $('measurementResult').textContent=`Габариты выделения\nA: ${a.toFixed(3)} м · B: ${b.toFixed(3)} м\nВысота: ${h.toFixed(3)} м\nВершин: ${points.length.toLocaleString('ru')}\nПроверь, что фон не попал в выделение.`;
 const shown=points.filter((_,i)=>i%Math.max(1,Math.ceil(points.length/6000))===0);marks.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints(shown.map(p=>new THREE.Vector3(...p))),new THREE.PointsMaterial({color:0xffd477,size:.01,depthTest:false})));
 const corners=[];for(let z=0;z<2;z++)for(let y=0;y<2;y++)for(let x=0;x<2;x++){const values=[x?result.high[0]:result.low[0],y?result.high[1]:result.low[1],z?result.high[2]:result.low[2]];corners.push(result.center.map((v,i)=>v+values.reduce((s,t,j)=>s+t*result.axes[j][i],0)))}
 for(const [i,j] of [[0,1],[0,2],[1,3],[2,3],[4,5],[4,6],[5,7],[6,7],[0,4],[1,5],[2,6],[3,7]])line([corners[i],corners[j]]);
 measurement={kind:'object',rawDimensions:result,dimensions:{...result,size:result.size.map(v=>v*scale)},calibrationFactor:scale,source:mode,scan:current?.id,accuracyVerified:false,depthMeters:shownDepth};
}
$('selectionDepth').onchange=selectObject;
function renderMeasurements(){$('measurements').replaceChildren();for(const original of project?.measurements||[]){const m=normalizedMeasurement(original);const item=document.createElement('div');item.className='measurement';const title=document.createElement('strong');title.textContent=m.name;const text=document.createElement('small');text.textContent=m.kind==='object'?m.dimensions.size.map(v=>v.toFixed(3)).join(' × ')+' м':m.value.toFixed(3)+(m.units==='m2'?' м²':' м');item.append(title,text);$('measurements').append(item)}}
$('saveMeasure').onclick=async()=>{if(!measurement||!project)return error('Сначала выполни измерение');try{const item={...measurement,id:crypto.randomUUID(),name:$('measurementName').value.trim()||'Измерение '+((project.measurements?.length||0)+1)};const items=[...(project.measurements||[]),item];await post('/api/measurements',{project:project.id,items});project.measurements=items;renderMeasurements();$('saved').textContent='Измерение сохранено';error('')}catch(e){error(e.message)}};
function downloadJSON(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('exportMeasures').onclick=()=>project&&downloadJSON('measurements.json',{project:project.name,units:'meters',accuracyVerified:false,calibration:project.calibration||null,measurements:(project.measurements||[]).map(normalizedMeasurement)});
$('exportMeasuresCSV').onclick=()=>{if(!project)return;const rows=[['Название','Тип','Размер / габариты','Единицы','Коэффициент','Точность подтверждена']];for(const item of project.measurements||[]){const m=normalizedMeasurement(item);rows.push([m.name,({distance:'Длина 3D',polyline:'Ломаная 3D',polygon:'Площадь пола',surface:'Площадь поверхности',object:'Габариты','plan-distance':'Длина по SVG','plan-area':'Площадь по SVG'}[m.kind]||m.kind),m.kind==='object'?m.dimensions.size.map(v=>v.toFixed(3)).join(' x '):m.value.toFixed(3),m.units||'m',m.calibrationFactor||1,'нет'])}const blob=new Blob(['\ufeff'+rows.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='measurement-schedule.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
function metricFactor(scan=current?.id){return project?.calibration?.scan===scan?project.calibration.factor:project?.baseline?.enabled?project.baseline.factor:1}
function normalizedMeasurement(m){const scale=metricFactor(m.scan),old=m.calibrationFactor||1;if(m.kind==='object'){const raw=m.rawDimensions||{...m.dimensions,size:m.dimensions.size.map(v=>v/old)};return {...m,rawDimensions:raw,calibrationFactor:scale,dimensions:{...raw,size:raw.size.map(v=>v*scale)}}}const power=m.units==='m2'?2:1,raw=m.rawValue??m.value/Math.pow(old,power);return {...m,rawValue:raw,calibrationFactor:scale,value:raw*Math.pow(scale,power)}}
function renderCalibration(){const base=project?.baseline;$('baselineExports').replaceChildren();for(const file of (base?.exports&&current&&base.exports.scan===current.id?base.exports.files:[])){const a=document.createElement('a');a.textContent=file;a.href=`/data/${current.id}/${file}`;a.download=file;$('baselineExports').append(a)}$('baselineExport').disabled=!base?.enabled||!current;$('baselineEnabled').checked=!!base?.enabled;$('baselineStatus').textContent=base?`Предварительный коэффициент ${base.factor.toFixed(6)}. Контур прошлого скана не согласуется одним масштабом: ${base.references.map(r=>`${r.rawMeters.toFixed(3)} → ${r.realMeters.toFixed(3)} м, остаток ${(r.residualMeters*1000).toFixed(0)} мм`).join('; ')}. Ручная калибровка текущего скана имеет приоритет.`:'Базовый профиль не задан';const c=project?.calibration;$('calibrationStatus').textContent=!c?(base?.enabled?'Базовая поправка по прошлой комнате. Точность текущего скана не проверена.':'Исходный масштаб скана. Контрольный размер не задан.'):`Коэффициент: ${c.factor.toFixed(6)}\n${c.reference.name}: ${c.reference.rawMeters.toFixed(3)} → ${c.reference.realMeters.toFixed(3)} м\n${c.scan===current?.id?'Для текущего скана':'Для другого скана проекта'}\nТочность до 3 см не подтверждена автоматически`;$('calibrationChecks').replaceChildren();for(const check of c?.checks||[]){const p=document.createElement('p');p.textContent=`${check.name}: отклонение ${(check.residualMeters*1000).toFixed(1)} мм`;p.className='hint';$('calibrationChecks').append(p)}$('calibrationExports').replaceChildren();for(const file of c?.exports||[]){const a=document.createElement('a');a.textContent=file;a.href=`/data/${c.scan}/${file}`;a.download=file;a.className='wide';$('calibrationExports').append(a)}}
async function calibrate(action){try{if(!project||!current)throw new Error('Выбери скан');if(action!=='reset'&&(picked.length!==2||mode==='plan'))throw new Error('Выбери ровно две точки инструментом «Расстояние» на 3D-скане');await post('/api/calibration',{project:project.id,scan:current.id,mode:action,points:picked.map(p=>[...p]),realMeters:Number($('calibrationReal').value),name:$('calibrationName').value||'Контрольный размер'});await loadProjects();updateMeasurement();error('')}catch(e){error(e.message)}}
$('calibrationSet').onclick=()=>calibrate('set');$('calibrationCheck').onclick=()=>calibrate('check');$('calibrationReset').onclick=()=>calibrate('reset');
async function refresh(){
 try{
  if(!project)return;const old=current;const loaded=await api(`/api/jobs?project=${project.id}`);jobs=loaded;renderJobs();if($('error').textContent==='Failed to fetch')error('');
  const running=jobs.find(j=>j.state==='running');$('progress').hidden=!running;$('progress').value=running?.progress||0;
  if(!busyUpload)$('status').textContent=running?.message||current?.message||'Выбери скан или импортируй файлы';
  $('sceneStatus').hidden=!running&&(!current||current.state==='done');$('sceneStatus').textContent=running?`${running.message} · ${running.progress}%`:current?.message||'';
  if(current){const updated=jobs.find(j=>j.id===current.id);if(updated){current=updated;updateInspector();if(old.state==='running'&&updated.state==='done'){for(const [key,root]of [...cache]){if(key.includes('forced')||key.includes('straightened')||key.includes('points')||key.endsWith('/difference')){scene.remove(root);dispose(root);cache.delete(key)}}await loadProjects();await show(updated.report.mesh?(updated.report.forced?'compareForced':'compare'):'points')}}}
  else if(jobs.length){const preferred=jobs.findLast(j=>(j.report?.points||0)>1000)||jobs.at(-1);await selectJob(preferred)}
  if(project.plan?.state==='running')await loadProjects();
 }catch(e){error(e.message)}
}
const mapIntegration=initMap({getProject:()=>project,getScan:()=>current?.id,getFactor:()=>metricFactor(),onOpen:()=>{if(flight.active)flight.set(false);$('floorplanStage').hidden=true;mode='map';$('viewMode').value='map';for(const id of ['compareLine','compareControl','beforeLabel','afterLabel','heatLegend'])$(id).hidden=true;$('variant').textContent='MPUNAV + скан · предварительная привязка';$('variant').dataset.ready='map'},onClose:()=>show(current?.report.mesh?'mesh':'points'),getPoints:()=>picked,getCloud:async()=>{if(!current?.report.mesh&&!current?.report.pointCloud)return [];const root=await getModel(current.report.mesh?'mesh.glb':'points.glb'),points=[];root.updateMatrixWorld(true);let count=0;root.traverse(o=>{count+=o.geometry?.attributes.position?.count||0});const stride=Math.max(1,Math.ceil(count/6000)),floor=new THREE.Box3().setFromObject(root).min.y;root.traverse(o=>{const p=o.geometry?.attributes.position;if(!p)return;for(let i=0;i<p.count;i+=stride){vector.fromBufferAttribute(p,i).applyMatrix4(o.matrixWorld);if(vector.y>floor+.1&&vector.y<floor+2.4)points.push(vector.toArray())}});return points},reloadProjects:loadProjects});
for(const key of ['importCompact','importFileButton','planUpload'])$(key).disabled=false;
try{await loadProjects();await refresh()}catch(e){error(e.message)}
setInterval(refresh,1800);
