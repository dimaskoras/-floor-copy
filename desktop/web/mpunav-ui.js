export function initMap({getProject,getPoints,getCloud,reloadProjects}){
 const $=id=>document.getElementById(id);let image=null,cloud=[],anchors=[];
 async function post(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),d=await r.json();if(!r.ok)throw new Error(d.error);return d}
 function status(text){$('mapStatus').textContent=text}
 function transform(){return {scale:Number($('mapScale').value),angle:Number($('mapAngle').value)*Math.PI/180,x:Number($('mapX').value),y:Number($('mapY').value)}}
 function mapPoint(p,t){const c=Math.cos(t.angle),s=Math.sin(t.angle);return [t.scale*(p[0]*c-p[2]*s)+t.x,t.scale*(p[0]*s+p[2]*c)+t.y]}
 function draw(){
  const p=getProject(),m=p?.mpunav;if(!m||!image)return;const canvas=$('mapCanvas'),ctx=canvas.getContext('2d'),[vx,vy,vw,vh]=m.viewBox;
  canvas.width=1400;canvas.height=Math.round(1400*vh/vw);ctx.fillStyle='#151820';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0,canvas.width,canvas.height);
  const t=transform(),scale=canvas.width/vw;ctx.fillStyle=`rgba(99,227,212,${Number($('mapOpacity').value)/100})`;
  for(const point of cloud){const q=mapPoint(point,t);ctx.fillRect((q[0]-vx)*scale,(q[1]-vy)*scale,2,2)}
  anchors.forEach((a,i)=>{ctx.beginPath();ctx.arc((a[0]-vx)*scale,(a[1]-vy)*scale,5,0,Math.PI*2);ctx.fillStyle='#f783cb';ctx.fill();ctx.fillText(String(i+1),(a[0]-vx)*scale+7,(a[1]-vy)*scale)});
 }
 function update(){const m=getProject()?.mpunav;$('mapOpen').disabled=!m;if(m){const t=m.transform||{scale:m.referenceScale||54.8,angle:0,x:m.viewBox[0]+m.viewBox[2]/2,y:m.viewBox[1]+m.viewBox[3]/2};$('mapScale').value=t.scale;$('mapAngle').value=t.angle*180/Math.PI;$('mapX').value=t.x;$('mapY').value=t.y;status(m.name+' · '+m.scaleNote)}else status('Карта не выбрана. Исходный сайт и граф маршрутов не изменяются.')}
 $('mapCatalog').onclick=async()=>{try{const r=await fetch('/api/mpunav/catalog'),data=await r.json();if(!r.ok)throw new Error(data.error);$('mapChoice').replaceChildren();for(const item of data){const o=document.createElement('option');o.value=item.name;o.textContent=item.name.replace('.svg','').replaceAll('-',' · ');$('mapChoice').append(o)}status('Доступно карт: '+data.length)}catch(e){status(e.message)}};
 $('mapLoad').onclick=async()=>{try{const p=getProject();if(!p)throw new Error('Сначала выбери проект');await post('/api/mpunav/map',{project:p.id,name:$('mapChoice').value});await reloadProjects();update()}catch(e){status(e.message)}};
 $('mapOpen').onclick=async()=>{try{const p=getProject();if(!p?.mpunav)return;cloud=await getCloud();anchors=p.mpunav.anchors||[];image=new Image();image.src=`/data/projects/${p.id}/mpunav.svg`;await image.decode();$('mapDialog').showModal();draw()}catch(e){status(e.message)}};
 $('mapClose').onclick=()=>$('mapDialog').close();$('mapReset').onclick=()=>{anchors=[];$('anchorHelp').textContent='Нажми две соответствующие точки карты.';draw()};
 $('mapCanvas').onclick=e=>{
  const m=getProject()?.mpunav,points=getPoints();if(!m||points.length<2){$('anchorHelp').textContent='Сначала отметь две точки на 3D-модели.';return}
  const r=$('mapCanvas').getBoundingClientRect();if(anchors.length>=points.length)anchors=[];
  anchors.push([m.viewBox[0]+(e.clientX-r.left)/r.width*m.viewBox[2],m.viewBox[1]+(e.clientY-r.top)/r.height*m.viewBox[3]]);
  if(anchors.length>=2){const a=points[0],b=points[1],u=anchors[0],v=anchors[1];const dx=b[0]-a[0],dz=b[2]-a[2],tx=v[0]-u[0],ty=v[1]-u[1],length=Math.hypot(dx,dz);if(length<.1){$('anchorHelp').textContent='Точки скана слишком близко.';return}const scale=Math.hypot(tx,ty)/length,angle=Math.atan2(ty,tx)-Math.atan2(dz,dx),c=Math.cos(angle),s=Math.sin(angle);$('mapScale').value=scale;$('mapAngle').value=angle*180/Math.PI;$('mapX').value=u[0]-scale*(a[0]*c-a[2]*s);$('mapY').value=u[1]-scale*(a[0]*s+a[2]*c);$('anchorHelp').textContent='Две точки совмещены. Это привязка, а не проверка точности.';if(anchors.length>=3&&points.length>=3){const projected=mapPoint(points[2],transform());const residual=Math.hypot(projected[0]-anchors[2][0],projected[1]-anchors[2][1])/scale;$('anchorHelp').textContent=`Контроль третьей точки: ${residual.toFixed(3)} м относительно SVG. Точность самой SVG-карты не подтверждена.`}}
  draw();
 };
 for(const id of ['mapScale','mapAngle','mapX','mapY','mapOpacity'])$(id).oninput=draw;
 $('mapSave').onclick=async()=>{try{const p=getProject();await post('/api/mpunav/save',{project:p.id,transform:transform(),anchors});status('Привязка сохранена в проекте');await reloadProjects()}catch(e){status(e.message)}};
 $('mapExport').onclick=async()=>{try{const p=getProject();await post('/api/mpunav/save',{project:p.id,transform:transform(),anchors});const data=await post('/api/mpunav/export',{project:p.id,points:await getCloud()});$('mapDownload').href=data.url;$('mapDownload').download='mpunav-with-scan.svg';$('mapDownload').hidden=false;status('Отдельный SVG подготовлен. Исходная карта не изменена.')}catch(e){status(e.message)}};
 return {update};
}
