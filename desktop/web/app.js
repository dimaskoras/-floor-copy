import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = id => document.getElementById(id);
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setClearColor(0x0c111b);
$('viewport').append(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(55,1,.01,1000);
camera.position.set(4,3,4);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff,0x778899,2));
const grid = new THREE.GridHelper(20,20,0x34445b,0x1e2a3d);
scene.add(grid);
const marks = new THREE.Group();scene.add(marks);
let model, current, mode='mesh', measuring=false, picked=[], loadTicket=0;
const ray = new THREE.Raycaster();ray.params.Points.threshold=.04;
const pointer = new THREE.Vector2();
new ResizeObserver(() => {
 const w=$('viewport').clientWidth,h=$('viewport').clientHeight;
 renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();
}).observe($('viewport'));
renderer.setAnimationLoop(()=>{controls.update();renderer.render(scene,camera)});

function error(message){$('error').textContent=message;$('error').hidden=!message}
function dispose(object){object.traverse(o=>{o.geometry?.dispose();if(o.material){for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose()}})}
function clearMarks(){for(const o of [...marks.children]){marks.remove(o);dispose(o)}picked=[];$('distance').textContent='Выбери две точки модели.'}
function fit(top=false){
 if(!model)return;
 const box=new THREE.Box3().setFromObject(model),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
 const extent=Math.max(size.x,size.y,size.z,1);
 controls.target.copy(center);
 camera.up.set(0,top?0:1,top?-1:0);
 camera.position.copy(center).add(top?new THREE.Vector3(0,extent*1.4,.001):new THREE.Vector3(extent,extent*.65,extent));
 camera.far=Math.max(100,extent*10);camera.updateProjectionMatrix();controls.update();
 grid.position.y=box.min.y-.02;
}
async function load(job,nextMode=mode){
 current=job;mode=nextMode;
 const ticket=++loadTicket;
 const file=mode==='mesh'&&job.report.mesh?'mesh.glb':'points.glb';
 try{
  const gltf=await new GLTFLoader().loadAsync(`/data/${job.id}/${file}`);
  if(ticket!==loadTicket){dispose(gltf.scene);return}
  if(model){scene.remove(model);dispose(model)}
  model=gltf.scene;
  model.traverse(o=>{if(o.isPoints){o.material.size=.025;o.material.sizeAttenuation=true}});
  scene.add(model);$('empty').hidden=true;clearMarks();fit();error('');
  $('exports').replaceChildren();
  for(const [label,name] of [['GLB',file],['PLY',file.replace('.glb','.ply')]]){
   const a=document.createElement('a');a.textContent=label;a.href=`/data/${job.id}/${name}`;a.download=name;$('exports').append(a);
  }
 }catch(e){error('Не удалось открыть модель: '+e.message)}
}
$('mesh').onclick=()=>current&&load(current,'mesh');
$('points').onclick=()=>current&&load(current,'points');
$('fit').onclick=()=>fit();$('top').onclick=()=>fit(true);
$('measure').onclick=()=>{measuring=!measuring;$('measure').setAttribute('aria-pressed',measuring);clearMarks()};
let down;
renderer.domElement.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY]});
renderer.domElement.addEventListener('pointerup',e=>{
 if(!measuring||!model||!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;
 const r=renderer.domElement.getBoundingClientRect();
 pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);
 ray.setFromCamera(pointer,camera);
 const hit=ray.intersectObject(model,true)[0];if(!hit)return;
 if(picked.length===2)clearMarks();
 // Points intersections return a ray position; use the actual measured vertex instead.
 const point=hit.object.isPoints ? new THREE.Vector3().fromBufferAttribute(hit.object.geometry.attributes.position,hit.index).applyMatrix4(hit.object.matrixWorld) : hit.point.clone();
 picked.push(point);
 const dot=new THREE.Mesh(new THREE.SphereGeometry(.035,12,12),new THREE.MeshBasicMaterial({color:0x77dccb,depthTest:false}));dot.position.copy(point);marks.add(dot);
 if(picked.length===2){
  marks.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(picked),new THREE.LineBasicMaterial({color:0x77dccb,depthTest:false})));
  $('distance').textContent=`${picked[0].distanceTo(picked[1]).toFixed(3)} м — проверь контрольным замером`;
 }else $('distance').textContent='Теперь выбери вторую точку.';
});
$('file').onchange=async e=>{
 const file=e.target.files[0];if(!file)return;
 $('status').textContent='Передаю архив…';$('progress').hidden=false;error('');
 try{
  const response=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/zip'},body:file});
  const data=await response.json();if(!response.ok)throw new Error(data.error);
  $('status').textContent='Началась обработка';
 }catch(e){error(e.message);$('progress').hidden=true}
 $('file').value='';
};
let autoLoaded = false;
async function refresh(){
 try{
  const response=await fetch('/api/jobs');if(!response.ok)throw new Error('Сервер недоступен');const jobs=await response.json();
  $('jobs').replaceChildren();
  for(const job of jobs){
   const button=document.createElement('button');
   button.textContent=job.state==='done'?`Участок ${job.id.slice(0,6)} · ${job.report.frames} кадров`:job.message;
   button.disabled=job.state!=='done';button.onclick=()=>load(job);$('jobs').append(button);
   if(job.state==='running'){$('status').textContent=job.message;$('progress').hidden=false;$('progress').value=job.progress}
  }
  if(!jobs.some(j=>j.state==='running')){
   $('progress').hidden=true;
   const last=jobs.at(-1);if(last)$('status').textContent=last.state==='error'?`Ошибка: ${last.message}`:'Обработка завершена';
  }
  const ready=jobs.find(j=>j.state==='done');if(ready&&!autoLoaded){autoLoaded=true;await load(ready)}
 }catch(e){$('status').textContent=e.message}
 setTimeout(refresh,1500);
}
refresh();
