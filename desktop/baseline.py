"""A provisional prior from a previous scan, not device calibration."""
import math


def fit_baseline(observed,planned):
    if len(observed)!=len(planned) or not observed or any(not math.isfinite(float(v)) or v<=0 for v in observed+planned):raise ValueError('Нужны положительные контрольные длины')
    factor=sum(a*b for a,b in zip(observed,planned))/sum(a*a for a in observed)
    return {'factor':factor,'enabled':True,'source':'previous-room-plan','accuracyVerified':False,
            'references':[{'rawMeters':a,'realMeters':b,'residualMeters':a*factor-b} for a,b in zip(observed,planned)],
            'note':'Предварительная единая поправка по контуру прошлого скана. Не исправляет неравномерные искажения и не подтверждает точность другого скана.'}
