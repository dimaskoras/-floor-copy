// Remove only triangles supported by tall architectural planes in the preview.
export function architecturalWalls(planes){return planes.filter(p=>p.kind==='vertical'&&p.areaM2>=.7&&p.bounds[1][1]-p.bounds[0][1]>=1.2)}
export function withoutWallFaces(position,index,planes,hiddenIds=null){
 const walls=architecturalWalls(planes).filter(p=>hiddenIds===null||hiddenIds.has(p.id)),kept=[];
 for(let i=0;i<index.length;i+=3){const a=index[i]*3,b=index[i+1]*3,c=index[i+2]*3,ux=position[b]-position[a],uy=position[b+1]-position[a+1],uz=position[b+2]-position[a+2],vx=position[c]-position[a],vy=position[c+1]-position[a+1],vz=position[c+2]-position[a+2],n=[uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx],length=Math.hypot(...n),center=[0,1,2].map(j=>(position[a+j]+position[b+j]+position[c+j])/3);
  const hidden=length>1e-12&&walls.some(p=>Math.abs(center.reduce((sum,v,j)=>sum+v*p.normal[j],p.constant))<.07&&Math.abs(n.reduce((sum,v,j)=>sum+v*p.normal[j],0))/length>.8);
  if(!hidden)kept.push(index[i],index[i+1],index[i+2]);
 }
 return new Uint32Array(kept);
}
