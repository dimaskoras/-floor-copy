"""Project observed scan photographs onto architectural planes, without moving vertices.

Only nearby, similarly oriented source triangles contribute. Unobserved pixels stay
neutral: this deliberately does not invent photographs behind furniture.
"""
import io
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt


class PhotoBaker:
    def __init__(self, mesh, pixels_per_meter=100, max_distance=.20):
        self.density=pixels_per_meter;self.max_distance=max_distance
        triangles=[];uvs=[];colors=[];images=[]
        for p in mesh.primitives:
            tex=mesh.doc.get('materials',[])[p.get('material',0)].get('pbrMetallicRoughness',{}).get('baseColorTexture') if mesh.doc.get('materials') else None
            if not tex or 'TEXCOORD_0' not in p['attributes']:continue
            if tex.get('texCoord',0)!=0 or tex.get('extensions'):raise ValueError('Преобразования UV исходной фотографии пока не поддерживаются')
            image=mesh.doc['images'][mesh.doc['textures'][tex['index']]['source']]
            if 'bufferView' not in image:raise ValueError('Для переноса фото нужны встроенные изображения GLB')
            view=mesh.doc['bufferViews'][image['bufferView']];offset=view.get('byteOffset',0)
            pixels=np.asarray(Image.open(io.BytesIO(mesh.binary[offset:offset+view['byteLength']])).convert('RGB'))
            v=mesh.array(p['attributes']['POSITION']);uv=mesh.array(p['attributes']['TEXCOORD_0'])
            f=mesh.array(p['indices']).reshape(-1,3) if 'indices' in p else np.arange(len(v)).reshape(-1,3)
            triangles.append(v[f]);uvs.append(uv[f]);colors.append(np.full(len(f),len(images),dtype=np.int32));images.append(pixels)
        self.images=images;self.observed=0;self.total=0
        if not images:return
        self.triangles=np.concatenate(triangles).astype(float);self.uv=np.concatenate(uvs);self.image_ids=np.concatenate(colors)
        cross=np.cross(self.triangles[:,1]-self.triangles[:,0],self.triangles[:,2]-self.triangles[:,0])
        self.normals=cross/np.maximum(np.linalg.norm(cross,axis=1)[:,None],1e-20)
        self.low=self.triangles.min(axis=1);self.high=self.triangles.max(axis=1)

    def patch(self, q, width, height, neutral):
        q=np.asarray(q);u=q[1]-q[0];v=q[3]-q[0]
        lu=np.linalg.norm(u);lv=np.linalg.norm(v);u=u/lu;v=v/lv;n=np.cross(u,v)
        # Axis aligned target planes make the broad phase cheap and deterministic.
        axis=int(np.argmax(abs(n)));plane=q[0,axis];lo=q.min(axis=0);hi=q.max(axis=0)
        eligible=(abs(self.normals[:,axis])>.85)&(self.low[:,axis]<plane+self.max_distance)&(self.high[:,axis]>plane-self.max_distance)
        for k in range(3):
            if k!=axis:eligible&=(self.low[:,k]<=hi[k])&(self.high[:,k]>=lo[k])
        result=np.empty((height,width,3),dtype=np.uint8);result[:]=neutral
        depth=np.full((height,width),np.inf,dtype=np.float32)
        for idx in np.flatnonzero(eligible):
            t=self.triangles[idx]-q[0];xy=np.column_stack((t@u/lu*width-.5,t@v/lv*height-.5))
            a,b,c=xy;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(den)<1e-10:continue
            mn=np.maximum(np.ceil(xy.min(axis=0)).astype(int),0);mx=np.minimum(np.floor(xy.max(axis=0)).astype(int),[width-1,height-1])
            if np.any(mx<mn):continue
            xx,yy=np.meshgrid(np.arange(mn[0],mx[0]+1),np.arange(mn[1],mx[1]+1))
            w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
            w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den;w2=1-w0-w1
            distance=abs(w0*t[0,axis]+w1*t[1,axis]+w2*t[2,axis])
            old=depth[yy,xx];mask=(w0>=-1e-7)&(w1>=-1e-7)&(w2>=-1e-7)&(distance<=self.max_distance)&(distance<old)
            if not mask.any():continue
            uv=w0[mask,None]*self.uv[idx,0]+w1[mask,None]*self.uv[idx,1]+w2[mask,None]*self.uv[idx,2]
            photo=self.images[self.image_ids[idx]];ph,pw=photo.shape[:2]
            # glTF UV origin is the top left. Bilinear sampling avoids stair steps.
            tx=np.clip(uv[:,0]*pw-.5,0,pw-1);ty=np.clip(uv[:,1]*ph-.5,0,ph-1)
            ix=tx.astype(int);iy=ty.astype(int);jx=np.minimum(ix+1,pw-1);jy=np.minimum(iy+1,ph-1)
            fx=(tx-ix)[:,None];fy=(ty-iy)[:,None]
            rgb=(photo[iy,ix]*(1-fx)+photo[iy,jx]*fx)*(1-fy)+(photo[jy,ix]*(1-fx)+photo[jy,jx]*fx)*fy
            result[yy[mask],xx[mask]]=np.clip(rgb,0,255).astype(np.uint8);depth[yy[mask],xx[mask]]=distance[mask]
        self.last_mask=np.isfinite(depth)
        self.observed+=int(self.last_mask.sum());self.total+=width*height
        return result

    def atlas(self, quads, neutral):
        if not self.images:return None
        # Keep one atlas per component, preserving the original mesh topology.
        density=self.density
        while True:
            boxes=[];x=y=row=0
            for q in quads:
                w=max(2,int(np.ceil(np.linalg.norm(q[1]-q[0])*density)));h=max(2,int(np.ceil(np.linalg.norm(q[3]-q[0])*density)))
                if x+w+4>4096:x=0;y+=row;row=0
                boxes.append((x+2,y+2,w,h));x+=w+4;row=max(row,h+4)
            if y+row<=4096 and all(w+4<=4096 and h+4<=4096 for _,_,w,h in boxes):break
            density*=.75
        aw=max(x+w+2 for x,y,w,h in boxes);ah=max(y+h+2 for x,y,w,h in boxes)
        canvas=np.empty((ah,aw,3),dtype=np.uint8);canvas[:]=neutral;uv=[]
        patches=[];samples=[]
        for q,(_,_,w,h) in zip(quads,boxes):
            patch=self.patch(q,w,h,neutral);mask=self.last_mask.copy();patches.append((patch,mask))
            if mask.any():samples.append(patch[mask][::max(1,int(mask.sum())//2000)])
        # Unseen regions stay solid, but match the observed paint/floor instead of
        # appearing as bright grey flakes. No image detail is invented there.
        fill=np.median(np.concatenate(samples),axis=0).astype(np.uint8) if samples else np.array(neutral,dtype=np.uint8)
        for (patch,mask),(x,y,w,h) in zip(patches,boxes):
            patch[~mask]=fill
            if mask.any() and not mask.all():
                distance,nearest=distance_transform_edt(~mask,return_indices=True)
                narrow=(~mask)&(distance<=3)
                patch[narrow]=patch[nearest[0,narrow],nearest[1,narrow]]
            canvas[y-2:y+h+2,x-2:x+w+2]=np.pad(patch,((2,2),(2,2),(0,0)),mode='edge')
            uv.extend([[x/aw,y/ah],[(x+w)/aw,y/ah],[(x+w)/aw,(y+h)/ah],[x/aw,(y+h)/ah]])
        out=io.BytesIO();Image.fromarray(canvas).save(out,format='JPEG',quality=94,subsampling=0)
        return out.getvalue(),np.array(uv,dtype='<f4')

    def report(self):
        return {'method':'nearby parallel source triangles projected to planes','sourcePhotoCount':len(self.images),
                'pixelsPerMeter':self.density,'maxProjectionDistanceMeters':self.max_distance,
                'observedPixelFraction':self.observed/max(1,self.total),'unobservedAppearance':'solid median color of observed component',
                'gapInterpolationMaxPixels':3,
                'geometryChanged':False}
