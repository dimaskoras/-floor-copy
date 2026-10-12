export function dimensions(points) {
 if(points.length<3)throw new Error('В выделении слишком мало точек');
 const center=points.reduce((a,p)=>a.map((v,i)=>v+p[i]),[0,0,0]).map(v=>v/points.length);
 // Minimum-area rectangle of the horizontal convex hull is less sensitive
 // to uneven vertex density than PCA axes.
 const ordered=points.map(p=>[p[0],p[2]]).sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
 const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
 const lower=[],upper=[];for(const p of ordered){while(lower.length>1&&cross(lower.at(-2),lower.at(-1),p)<=0)lower.pop();lower.push(p)}for(const p of [...ordered].reverse()){while(upper.length>1&&cross(upper.at(-2),upper.at(-1),p)<=0)upper.pop();upper.push(p)}
 const hull=lower.slice(0,-1).concat(upper.slice(0,-1));let angle=0,best=Infinity;
 for(let i=0;i<hull.length;i++){const a=hull[i],b=hull[(i+1)%hull.length],theta=Math.atan2(b[1]-a[1],b[0]-a[0]),c=Math.cos(theta),s=Math.sin(theta);let x0=Infinity,x1=-Infinity,z0=Infinity,z1=-Infinity;for(const p of hull){const x=p[0]*c+p[1]*s,z=-p[0]*s+p[1]*c;x0=Math.min(x0,x);x1=Math.max(x1,x);z0=Math.min(z0,z);z1=Math.max(z1,z)}const area=(x1-x0)*(z1-z0);if(area<best){best=area;angle=theta}}
 const c=Math.cos(angle),s=Math.sin(angle);
 const axes=[[c,0,s],[-s,0,c],[0,1,0]];
 const low=[Infinity,Infinity,Infinity],high=[-Infinity,-Infinity,-Infinity];
 for(const p of points)for(let j=0;j<3;j++){const t=p.reduce((v,x,i)=>v+(x-center[i])*axes[j][i],0);low[j]=Math.min(low[j],t);high[j]=Math.max(high[j],t)}
 return {center,axes,low,high,size:high.map((v,i)=>v-low[i]),pointCount:points.length};
}
export function distance(a,b){return Math.hypot(...a.map((v,i)=>v-b[i]))}
export function polygonArea(points){
 let sum=0;for(let i=0;i<points.length;i++){const a=points[i],b=points[(i+1)%points.length];sum+=a[0]*b[2]-b[0]*a[2]}return Math.abs(sum)/2;
}
