import assert from 'node:assert/strict';
import {dimensions,distance,polygonArea,surfaceArea} from './measurements.js';
assert.equal(distance([0,0,0],[3,4,0]),5);
assert.equal(polygonArea([[0,0,0],[2,0,0],[2,0,3],[0,0,3]]),6);
const angle=.43,c=Math.cos(angle),s=Math.sin(angle),points=[];
for(const x of [-1,1])for(const z of [-.5,.5])for(const y of [0,.75])points.push([x*c-z*s+5,y,x*s+z*c-2]);
const result=dimensions(points);
const horizontal=result.size.slice(0,2).sort((a,b)=>a-b);
assert.ok(Math.abs(horizontal[0]-1)<1e-8);assert.ok(Math.abs(horizontal[1]-2)<1e-8);assert.ok(Math.abs(result.size[2]-.75)<1e-8);
console.log('Distance, polygon area and rotated object dimensions: passed');

assert.equal(surfaceArea([[0,0,0],[2,0,0],[2,3,0],[0,3,0]]).area,6);assert.equal(surfaceArea([[0,0,0],[2,0,0],[2,3,0],[0,3,0]]).maximumPlaneDeviation,0);assert.equal(surfaceArea([[0,0,0],[0,0,3],[2,0,3],[2,0,0]]).area,6);
