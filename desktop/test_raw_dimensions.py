import unittest
from raw_dimensions import dimensions_from_planes


class RawDimensionTests(unittest.TestCase):
    def test_source_metres_without_calibration(self):
        planes=[]
        for axis,value in [(0,-5),(0,4),(2,-6),(2,6),(1,0),(1,3.2)]:
            n=[0,0,0];n[axis]=1
            planes.append({'id':len(planes),'kind':'horizontal' if axis==1 else 'vertical','normal':n,'constant':-value,'areaM2':30})
        r=dimensions_from_planes(planes)
        self.assertEqual(r['factor'],1);self.assertFalse(r['accuracyVerified'])
        self.assertEqual([round(i['meters'],6) for i in r['items']],[9,12,3.2])
        self.assertEqual(r['items'][0]['planeIds'],[0,1])

    def test_missing_planes_are_not_invented(self):
        self.assertEqual(dimensions_from_planes([])['items'],[])


if __name__=='__main__':unittest.main()
