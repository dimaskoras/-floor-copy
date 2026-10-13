import assert from 'node:assert/strict';
import {mapPoint,fitTwoPoints,planMetric} from './map-math.js';
const t=fitTwoPoints([[1,0,2],[3,0,2]],[[100,200],[100,300]]);
for(const [p,q] of [[[1,0,2],[100,200]],[[3,0,2],[100,300]]])assert.ok(Math.hypot(...mapPoint(p,t).map((v,i)=>v-q[i]))<1e-8);
assert.equal(planMetric([[0,0],[100,0]],50,1.1).value,2.2);
assert.ok(Math.abs(planMetric([[0,0],[100,0],[100,150],[0,150]],50,1.1,true).value-7.26)<1e-8);
assert.equal(planMetric([[0,0],[100,0]],50,1,true),null);
assert.throws(()=>fitTwoPoints([[0,0,0],[0,1,0]],[[0,0],[10,10]]));
console.log('Map fit, calibrated distances, calibrated areas and invalid anchors: passed');
