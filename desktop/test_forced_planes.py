import unittest
import numpy as np
from forced_planes import project_architecture
from planar import face_data


def patch(kind='floor',offset=0):
    a,b=np.meshgrid(np.linspace(0,2,20),np.linspace(0,3,20))
    wave=.03*np.sin(a*np.pi)*np.cos(b*np.pi)
    v=np.c_[a.ravel(),wave.ravel(),b.ravel()] if kind=='floor' else np.c_[offset+wave.ravel(),b.ravel(),a.ravel()]
    f=[]
    for j in range(19):
        for i in range(19):
            k=j*20+i;f.extend([[k,k+1,k+20],[k+1,k+21,k+20]])
    p={'id':0,'kind':'horizontal' if kind=='floor' else 'vertical','normal':[0,1,0] if kind=='floor' else [1,0,0],
       'constant':-offset,'areaM2':6,'bounds':[v.min(axis=0).tolist(),v.max(axis=0).tolist()]}
    return v,np.array(f),p


class ForcedTests(unittest.TestCase):
    def test_flattens_centimeter_waves_without_folds(self):
        v,f,p=patch();out,planes,r=project_architecture(v,f,[p],np.zeros(len(f),dtype=int))
        self.assertLess(np.ptp(out[:,1]),1e-9)
        np.testing.assert_array_equal(out[:,[0,2]],v[:,[0,2]])
        _,n,a=face_data(v,f);_,q,b=face_data(out,f)
        self.assertTrue((np.einsum('ij,ij->i',n,q)>0).all())
        self.assertLessEqual(r['maximumShiftMm'],100)
        self.assertGreater(r['movedVertices'],100)

    def test_parallel_walls_retain_mean_separation(self):
        a,fa,pa=patch('wall');b,fb,pb=patch('wall',5);pb['id']=1
        v=np.vstack([a,b]);f=np.vstack([fa,fb+len(a)]);labels=np.r_[np.zeros(len(fa),int),np.ones(len(fb),int)]
        out,_,_=project_architecture(v,f,[pa,pb],labels)
        self.assertLess(np.ptp(out[:len(a),0]),1e-9)
        self.assertLess(np.ptp(out[len(a):,0]),1e-9)
        self.assertAlmostEqual(out[len(a):,0].mean()-out[:len(a),0].mean(),5,places=8)

    def test_unsupported_furniture_is_untouched(self):
        v,f,p=patch();out,planes,r=project_architecture(v,f,[p],np.full(len(f),-1,int))
        np.testing.assert_array_equal(v,out);self.assertEqual(planes,[])

    def test_seam_duplicates_receive_identical_projection(self):
        v,f,p=patch();points=np.vstack([v,v]);faces=np.vstack([f,f+len(v)])
        out,_,_=project_architecture(points,faces,[p],np.zeros(len(faces),int))
        np.testing.assert_array_equal(out[:len(v)],out[len(v):])


if __name__=='__main__':unittest.main()
