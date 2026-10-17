"""Convex polygon separating-axis overlap test for independent page surfaces."""
def overlaps(a,b):
    for polygon in (a,b):
        for i,p in enumerate(polygon):
            q=polygon[(i+1)%len(polygon)];axis=(-(q[1]-p[1]),q[0]-p[0])
            pa=[x*axis[0]+y*axis[1] for x,y in a];pb=[x*axis[0]+y*axis[1] for x,y in b]
            if max(pa)<=min(pb) or max(pb)<=min(pa):return False
    return True
