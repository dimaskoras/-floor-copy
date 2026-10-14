// Camera navigation changes only the view, never scan coordinates.
export function movement(keys,yaw,pitch,dt,speed=1.5){
 const forward=Number(keys.has('KeyW'))-Number(keys.has('KeyS'));
 const right=Number(keys.has('KeyD'))-Number(keys.has('KeyA'));
 const up=Number(keys.has('KeyE'))-Number(keys.has('KeyQ'));
 const x=-Math.sin(yaw)*Math.cos(pitch)*forward+Math.cos(yaw)*right;
 const y=Math.sin(pitch)*forward+up;
 const z=-Math.cos(yaw)*Math.cos(pitch)*forward-Math.sin(yaw)*right;
 const norm=Math.max(1,Math.hypot(x,y,z)),step=Math.min(.05,Math.max(0,dt))*speed;
 return [x/norm*step,y/norm*step,z/norm*step];
}
export function freeCamera(THREE,camera,controls,canvas,onStatus){
 let active=false,yaw=0,pitch=0,looking=null;const keys=new Set();
 canvas.tabIndex=0;canvas.setAttribute('aria-label','3D-просмотр: WASD, Q/E, правая кнопка для осмотра');
 const clear=()=>{keys.clear();looking=null};
 function set(enabled){clear();active=enabled;if(active){camera.up.set(0,1,0);const e=new THREE.Euler().setFromQuaternion(camera.quaternion,'YXZ');yaw=e.y;pitch=e.x;controls.enabled=false;canvas.focus()}else{controls.target.copy(camera.position).add(camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(2));controls.enabled=true}onStatus(active)}
 canvas.addEventListener('keydown',e=>{if(!active)return;if(e.code==='Escape'){set(false);return}if(['KeyW','KeyA','KeyS','KeyD','KeyQ','KeyE','ShiftLeft','ShiftRight'].includes(e.code)){keys.add(e.code);e.preventDefault()}});
 canvas.addEventListener('keyup',e=>keys.delete(e.code));canvas.addEventListener('blur',clear);window.addEventListener('blur',clear);
 canvas.addEventListener('pointerdown',e=>{if(!active)return;canvas.focus();if(e.button===2){looking={id:e.pointerId,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);e.preventDefault()}});
 canvas.addEventListener('pointermove',e=>{if(!active||!looking||looking.id!==e.pointerId)return;yaw-=(e.clientX-looking.x)*.003;pitch=THREE.MathUtils.clamp(pitch-(e.clientY-looking.y)*.003,-Math.PI/2+.01,Math.PI/2-.01);looking.x=e.clientX;looking.y=e.clientY;camera.quaternion.setFromEuler(new THREE.Euler(pitch,yaw,0,'YXZ'))});
 canvas.addEventListener('pointerup',e=>{if(looking?.id===e.pointerId)looking=null});canvas.addEventListener('pointercancel',clear);
 canvas.addEventListener('contextmenu',e=>{if(active)e.preventDefault()});
 return {set,get active(){return active},update(dt){if(!active)return;const d=movement(keys,yaw,pitch,dt,keys.has('ShiftLeft')||keys.has('ShiftRight')?4.5:1.5);camera.position.add(new THREE.Vector3(...d));onStatus(true,camera.position)}};
}
