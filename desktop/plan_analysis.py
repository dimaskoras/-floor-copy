"""Local raster floor-plan proposal: Windows OCR + line extraction.

The result is a draft. OCR dimensions and wall classification are not surveys.
"""
import asyncio
import json
import re
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from reconstruct import write_glb
from project_store import atomic_json


async def ocr(path):
    from winrt.windows.storage import StorageFile,FileAccessMode
    from winrt.windows.graphics.imaging import BitmapDecoder,BitmapPixelFormat,BitmapAlphaMode
    from winrt.windows.media.ocr import OcrEngine
    file=await StorageFile.get_file_from_path_async(str(Path(path).resolve()))
    stream=await file.open_async(FileAccessMode.READ)
    decoder=await BitmapDecoder.create_async(stream)
    bitmap=await decoder.get_software_bitmap_converted_async(BitmapPixelFormat.BGRA8,BitmapAlphaMode.PREMULTIPLIED)
    engine=OcrEngine.try_create_from_user_profile_languages()
    if engine is None:raise ValueError('В Windows не установлен язык для распознавания текста')
    result=await engine.recognize_async(bitmap)
    words=[]
    for line in result.lines:
        for word in line.words:
            r=word.bounding_rect
            words.append({'text':word.text,'x':r.x,'y':r.y,'w':r.width,'h':r.height})
    return words


def boxes_glb(segments,scale,height,path):
    vertices=[];faces=[]
    for x1,y1,x2,y2 in segments:
        a=np.array([x1,y1])*scale;b=np.array([x2,y2])*scale
        tangent=b-a;length=np.linalg.norm(tangent)
        if length<.1:continue
        normal=np.array([-tangent[1],tangent[0]])/length*.05
        offset=len(vertices)
        for level in [0,height]:
            for p in [a-normal,b-normal,b+normal,a+normal]:vertices.append([p[0],level,p[1]])
        faces.extend((np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])+offset).tolist())
    if not vertices:raise ValueError('Не найдены стены для черновой модели')
    v=np.array(vertices,dtype='<f4');v[:,[0,2]]-=v[:,[0,2]].mean(axis=0)
    write_glb(path,v,np.tile(np.array([80,170,160],dtype='u1'),(len(v),1)),np.array(faces,dtype='<u4'))


def analyze_plan(source,destination,manual_scale=None):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    source=Path(source)
    if source.suffix.lower()=='.pdf':
        import pymupdf
        with pymupdf.open(source) as pdf:
            if not len(pdf):raise ValueError('PDF пуст')
            page=pdf[0].get_pixmap(matrix=pymupdf.Matrix(2,2))
            page.save(str(destination/'plan.png'))
        image=Image.open(destination/'plan.png').convert('RGB')
    else:image=Image.open(source).convert('RGB')
    if max(image.size)>3500:
        image.thumbnail((3500,3500))
    image.save(destination/'plan.png')
    rgb=np.array(image);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    dark=(gray<170).astype('u1')*255
    h,w=gray.shape
    horizontal=cv2.morphologyEx(dark,cv2.MORPH_OPEN,np.ones((1,max(35,w//14)),np.uint8))
    vertical=cv2.morphologyEx(dark,cv2.MORPH_OPEN,np.ones((max(35,h//18),1),np.uint8))
    edges=cv2.Canny(cv2.bitwise_or(horizontal,vertical),40,120)
    detected=cv2.HoughLinesP(edges,1,np.pi/180,threshold=35,minLineLength=max(45,min(w,h)//10),maxLineGap=12)
    segments=[]
    if detected is not None:
        for row in detected.reshape(-1,4):
            x1,y1,x2,y2=map(int,row)
            if abs(x1-x2)>5 and abs(y1-y2)>5:continue
            mid=np.array([(x1+x2)/2,(y1+y2)/2])
            if any(np.linalg.norm(mid-np.array([(a+c)/2,(b+d)/2]))<12 and (abs(x1-x2)<5)==(abs(a-c)<5) for a,b,c,d in segments):continue
            segments.append([x1,y1,x2,y2])
    words=[];ocr_error=None
    try:words=asyncio.run(ocr(destination/'plan.png'))
    except Exception as error:ocr_error=str(error)
    dimensions=[];scales=[]
    for word in words:
        match=re.fullmatch(r'(\d{1,2})[.,](\d{2})',word['text'])
        if not match:continue
        value=float(match[1]+'.'+match[2])
        if not .4<value<15:continue
        x,y=word['x']+word['w']/2,word['y']+word['h']/2
        possible=[(a+c)/2 for a,b,c,d in segments if abs(a-c)<5 and min(b,d)-30<=y<=max(b,d)+30]
        left=[v for v in possible if v<x-10];right=[v for v in possible if v>x+10]
        dimension=dict(word,valueMeters=value)
        if left and right:
            span=min(right)-max(left);ratio=value/span
            if .001<ratio<.1:scales.append(ratio);dimension['proposedMetersPerPixel']=ratio
        dimensions.append(dimension)
    scale=None;confidence='unavailable'
    if manual_scale is not None:
        if not .0001<float(manual_scale)<1:raise ValueError('Некорректный масштаб плана')
        scale=float(manual_scale);confidence='user supplied'
    elif scales:
        cluster=max(([s for s in scales if abs(s/t-1)<.12] for t in scales),key=len)
        if len(cluster)>=2:scale=float(np.median(cluster));confidence='proposal, requires review'
    overlay=rgb.copy()
    for x1,y1,x2,y2 in segments:cv2.line(overlay,(x1,y1),(x2,y2),(20,170,140),3)
    Image.fromarray(overlay).save(destination/'plan-analysis.png')
    if scale and segments:boxes_glb(segments,scale,2.7,destination/'plan-model.glb')
    report={'segmentsPixels':segments,'recognizedDimensions':dimensions,'ocrWords':words,
            'ocrError':ocr_error,'metersPerPixel':scale,'scaleStatus':confidence,'model':bool(scale and segments),
            'assumedWallHeightMeters':2.7,'assumedWallThicknessMeters':.1,'accuracyVerified':False,
            'warnings':['Автоматический черновик: линии могут быть стенами, размерными линиями или мебелью.',
                        'Масштаб OCR требует проверки; высота и толщина стен заданы условно.',
                        'Проёмы и комнаты не распознаны надёжно. Модель плана не привязана автоматически к скану.']}
    atomic_json(destination/'plan-analysis.json',report)
    return report
