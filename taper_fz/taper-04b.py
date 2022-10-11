#!/usr/bin/env python

# Taper for pcbnew using filled zones
# easyw
#
# Based 
# on Teardrops for PCBNEW by Niluje 2019 thewireddoesntexist.org
# on kicad Toolbox vy aschaller 

import os
import sys
from math import cos, acos, sin, asin, tan, atan2, sqrt, pi, degrees, radians
from pcbnew import ToMM, FromMM, wxPoint, GetBoard, ZONE_SETTINGS
from pcbnew import ZONE_FILLER
import pcbnew
import wx

if hasattr(pcbnew,'ZONE_CONTAINER'):
    from pcbnew import ZONE_CONTAINER
else:
    from pcbnew import ZONE
SMOOTHING_FILLET = ZONE_SETTINGS.SMOOTHING_FILLET


def wxLogDebug(msg,show):
    """printing messages only if show is omitted or True"""
    if show:
        wx.LogMessage(msg)
#

##global __version__
##__version__ = "0.0.4"

ToUnits = ToMM
FromUnits = FromMM

MAGIC_TAPER_ZONE_ID = 0x4484

dbg = False

def dummy():
    pass
##
def __Zone(board, points, track):
    """Add a zone to the board"""
    if hasattr(pcbnew, 'ZONE_CONTAINER'): # kv5
        z = ZONE_CONTAINER(board)
        z.SetZoneClearance(track.GetClearance())
    else: # kv6
        z = ZONE(board)
        z.SetLocalClearance(track.GetLocalClearance(track.GetClass()))
    # Add zone properties
    z.SetLayer(track.GetLayer())
    z.SetNetCode(track.GetNetCode())
    
    z.SetMinThickness(25400)  # The minimum
    z.SetPadConnection(2)  # 2 -> solid
    z.SetIsFilled(True)
    z.SetPriority(MAGIC_TAPER_ZONE_ID)  # MAGIC_TEARDROP_ZONE_ID)
    ol = z.Outline()
    ol.NewOutline()

    for p in points:
        ol.Append(p.x, p.y)

    # sys.stdout.write("+")
    return z
##
def __Bezier(p1, p2, p3, p4, n=20.0):
    n = float(n)
    pts = []
    for i in range(int(n)+1):
        t = i/n
        a = (1.0 - t)**3
        b = 3.0 * t * (1.0-t)**2
        c = 3.0 * t**2 * (1.0-t)
        d = t**3

        x = int(a * p1[0] + b * p2[0] + c * p3[0] + d * p4[0])
        y = int(a * p1[1] + b * p2[1] + c * p3[1] + d * p4[1])
        pts.append(wxPoint(x, y))
    return pts
##
def __PointDistance(a,b):
    """Distance between two points"""
    return sqrt((a[0]-b[0])*(a[0]-b[0]) + (a[1]-b[1])*(a[1]-b[1]))
##
def __ComputeCurved(vpercent, w, vec, pad, pts, segs):
    """Compute the curves part points"""

    # A and B are points on the track
    # C and E are points on the via
    # D is midpoint behind the via centre

    # radius = via[1]/2
    radius = pad.GetSize().x/2
    
    minVpercent = float(w*2) / float(pad.GetSize().x) # via[1])
    weaken = (vpercent/100.0  -minVpercent) / (1-minVpercent) / radius

    biasBC = 0.5 * __PointDistance( pts[1], pts[2] )
    biasAE = 0.5 * __PointDistance( pts[4], pts[0] )

    vecC = pts[2] - pad.GetPosition() # via[0]
    tangentC = [ pts[2][0] - vecC[1]*biasBC*weaken,
                 pts[2][1] + vecC[0]*biasBC*weaken ]
    vecE = pts[4] - pad.GetPosition() # via[0]
    tangentE = [ pts[4][0] + vecE[1]*biasAE*weaken,
                 pts[4][1] - vecE[0]*biasAE*weaken ]

    tangentB = [pts[1][0] - vec[0]*biasBC, pts[1][1] - vec[1]*biasBC]
    tangentA = [pts[0][0] - vec[0]*biasAE, pts[0][1] - vec[1]*biasAE]

    curve1 = __Bezier(pts[1], tangentB, tangentC, pts[2], n=segs)
    curve2 = __Bezier(pts[4], tangentE, tangentA, pts[0], n=segs)

    return curve1 + [pts[3]] + curve2
##
def __ComputeCurvedTracks(vpercent, w1, vec, w2, end2, pts, segs):
    """Compute the curves part points"""

    # A and B are points on the track
    # C and E are points on the via
    # D is midpoint behind the via centre

    # w2= track.GetWidth()
    # radius = via[1]/2
    radius = w2 #/2
    
    minVpercent = float(w1*2) / float(w2) # via[1])
    weaken = (vpercent/100.0  -minVpercent) / (1-minVpercent) / radius

    biasBC = 0.5 * __PointDistance( pts[1], pts[2] )
    biasAE = 0.5 * __PointDistance( pts[4], pts[0] )

    vecC = pts[2] - end2 #track.GetEnd() # via[0]
    tangentC = [ pts[2][0] - vecC[1]*biasBC*weaken,
                 pts[2][1] + vecC[0]*biasBC*weaken ]
    vecE = pts[4] - end2 #track.GetEnd() # via[0]
    tangentE = [ pts[4][0] + vecE[1]*biasAE*weaken,
                 pts[4][1] - vecE[0]*biasAE*weaken ]

    tangentB = [pts[1][0] - vec[0]*biasBC, pts[1][1] - vec[1]*biasBC]
    tangentA = [pts[0][0] - vec[0]*biasAE, pts[0][1] - vec[1]*biasAE]

    curve1 = __Bezier(pts[1], tangentB, tangentC, pts[2], n=segs)
    curve2 = __Bezier(pts[4], tangentE, tangentA, pts[0], n=segs)

    return curve1 + [pts[3]] + curve2
##
def __NormalizeVector(pt):
    """Make vector unit length"""
    norm = sqrt(pt.x * pt.x + pt.y * pt.y)
    return [t / norm for t in pt]
## 
def __ComputePoints(track, pad, segs):
    """Compute all taper points"""
    hpercent=1; vpercent=100; noBulge=True
    start = track.GetStart()
    end = track.GetEnd()
    module = pad.GetParent()

    # ensure that start is at the via/pad end
    if (__PointDistance(end, pad.GetPosition()) < __PointDistance(start, pad.GetPosition())): # via[0]) < radius:
        start, end = end, start
    # if __PointDistance(end, pad.GetPosition()) < radius: # via[0]) < radius:
    #     start, end = end, start

    # get normalized track vector
    # it will be used a base vector pointing in the track direction
    vecT = __NormalizeVector(end - start)
    trackAngle = atan2(vecT[1],vecT[0])
    if trackAngle > pi:
        trackAngle -=2*pi
    if trackAngle < -pi:
        trackAngle +=2*pi
    trackAngle=degrees(trackAngle)    
    wxLogDebug('trackAngle='+str(trackAngle),dbg)
    #wxLogDebug('vecT='+str(vecT),dbg)
    
    sx = pad.GetSize().x
    sy = pad.GetSize().y
    
    # use an angle range
    if abs(module.GetOrientationDegrees()) == 90 or abs(module.GetOrientationDegrees()) == 270:
        nsx = sx
        nsy  = sy
    else:
        nsx = sy
        nsy  = sx
    if (abs(trackAngle) >= 60 and abs(trackAngle) <= 120) or (abs(trackAngle) >= 240 and abs(trackAngle) <= 300):
        nsx = nsy
        nsy  = nsx
    else:
        nsx = nsx
        nsy  = nsy
        
    radius = nsx/2 # via[1]/2.0
    targetLength = nsy*(hpercent/100.0) # via[1]*(hpercent/100.0)
    wxLogDebug('targetLength='+str(ToMM(targetLength)),dbg)
    
    w = track.GetWidth()/2

    if vpercent > 100:
        vpercent = 100

    # Find point of intersection between track and edge of via
    # This normalizes teardrop lengths
    bdelta = FromMM(0.01)
    backoff=0
    while backoff<radius:
        np = start + wxPoint( vecT[0]*backoff, vecT[1]*backoff )
        if __PointDistance(np, pad.GetPosition()) >= radius: # via[0]) >= radius:
            break
        backoff += bdelta
    start=np

    # vec now points from via to intersect point
    vec = __NormalizeVector(start - pad.GetPosition()) # via[0])

    # choose a teardrop length
    # targetLength = pad.GetSize().x*(hpercent/100.0) # via[1]*(hpercent/100.0)
    n = min(targetLength, track.GetLength() - backoff)
    consumed = 0

    # if shortened, shrink width too
    if n+consumed < targetLength:
        minVpercent = 100* float(w) / float(radius)
        vpercent = vpercent*n/targetLength + minVpercent*(1-n/targetLength)

    # find point on the track, sharp end of the teardrop
    pointB = start + wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
    pointA = start + wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w )
    #pointB = wxPoint(int(start.x-0.15*radius),int(start.y-0.15*radius)) + wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
    # Introduce a last point in order to cover the via centre.
    # If not, the zone won't be filled or not connected
    pointF = start + wxPoint(int(vecT[0]*+0.15*w), int(vecT[1]*+0.15*w))

    # In some cases of very short, eccentric tracks the points can end up
    # inside the teardrop. If this happens just cancel adding it
    if ( __PointDistance(pointA, pad.GetPosition()) < radius or
         __PointDistance(pointB, pad.GetPosition()) < radius ):
        return False
    # if ( __PointDistance(pointA, via[0]) < radius or
    #      __PointDistance(pointB, via[0]) < radius ):
    #     return False

    # via side points

    # angular positions of where the teardrop meets the via
    dC = asin(vpercent/100.0)
    dE = -dC

    if noBulge:
        # find (signed) angle between track and teardrop
        offAngle = atan2(vecT[1],vecT[0]) - atan2(vec[1],vec[0])
        if offAngle > pi:
            offAngle -=2*pi
        if offAngle < -pi:
            offAngle +=2*pi

        if offAngle+dC > pi/2:
            dC = pi/2 - offAngle

        if offAngle+dE < -pi/2:
            dE = -pi/2 - offAngle
        #wxLogDebug('offAngle='+str(degrees(offAngle)),dbg)
        
    vecC = [vec[0]*cos(dC)+vec[1]*sin(dC), -vec[0]*sin(dC)+vec[1]*cos(dC)]
    vecE = [vec[0]*cos(dE)+vec[1]*sin(dE), -vec[0]*sin(dE)+vec[1]*cos(dE)]

    pointC = pad.GetPosition() + wxPoint(int(vecC[0] * radius), int(vecC[1] * radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
    pointE = pad.GetPosition() + wxPoint(int(vecE[0] * radius), int(vecE[1] * radius)) # - wxPoint(int(vec[0]*-0.25*nsy), int(vec[1]*-0.25*nsy))
    # pointC = via[0] + wxPoint(int(vecC[0] * radius), int(vecC[1] * radius))
    # pointE = via[0] + wxPoint(int(vecE[0] * radius), int(vecE[1] * radius))

    # Introduce a last point in order to cover the via centre.
    # If not, the zone won't be filled
    pointD = pad.GetPosition() + wxPoint(int(vec[0]*-0.15*radius), int(vec[1]*-0.15*radius))
    # pointD = via[0] + wxPoint(int(vec[0]*-0.5*radius), int(vec[1]*-0.5*radius))

    pts = [pointA, pointB, pointC, pointD, pointE]
    #pts = [pointA, pointB, pointF, pointC, pointD, pointE]
    if segs > 2:
        pts = __ComputeCurved(vpercent, w, vecT, pad, pts, segs)
        # Introduce a last point in order to cover the via centre.
        # if not it may not be connected
        pts = [pointF]+pts
        #for i,p in enumerate(pts):
        #    if i> 0:
        #        pts_n.append(p)

    return pts
##

def __ComputePointsTracks(track1, track2, segs):
    """Compute all taper points for tracks"""
    hpercent=1; vpercent=100; noBulge=True
    start1 = track1.GetStart()
    end1 = track1.GetEnd()
    start2 = track2.GetStart()
    end2 = track2.GetEnd()
    w1 = track1.GetWidth()/2
    w2 = track2.GetWidth()/2
    if w1 == w2:
        return False
    wxLogDebug('start1='+str(start1)+' end1='+str(end1)+' start2='+str(start2)+' end2='+str(end2) ,dbg)
    # ensure that start1, end2 are at the tracks common
    common = None
    if (start1 == start2):
        common = start1
        start2, end2 = end2, start2
        wxLogDebug('1 ',dbg)
    elif (start1 == end2):
        common = start1
        #start2, end2 = end2, start2
        wxLogDebug('2 ',dbg)
    elif (end1 == end2):
        common = end1
        start1, end1 = end1, start1
        start2, end2 = end2, start2
        wxLogDebug('3 ',dbg)
    elif (end1 == start2):
        common = end1
        start1, end1 = end1, start1
        start2, end2 = end2, start2
        wxLogDebug('4 ',dbg)
    else:
        # tracks detached
        # ensure that start is at the common point [or the nearest TBD]
        d_min = min(__PointDistance(start1, end2), __PointDistance(start1, start2), __PointDistance(end1, start2), __PointDistance(end1, end2)) 
        if (__PointDistance(start1, start2) == d_min):
            start2, end2 = end2, start2
            wxLogDebug('a ',dbg)
        elif(__PointDistance(end1, start2) == d_min):
            start1, end1 = end1, start1
            start2, end2 = end2, start2            
            wxLogDebug('b ',dbg)
        elif(__PointDistance(end1, end2) == d_min):
            start1, end1 = end1, start1
            #start2, end2 = end2, start2
            wxLogDebug('c ',dbg)
        else: # start1, end2
            wxLogDebug('d ',dbg)
    if common is not None:
        wx.LogMessage('Select one Track & one Pad')
    # get normalized track vectors
    # it will be used a base vector pointing in the track direction
    vecT1 = __NormalizeVector(end1 - start1)
    trackAngle1 = atan2(vecT1[1],vecT1[0])
    if trackAngle1 > pi:
        trackAngle1 -=2*pi
    if trackAngle1 < -pi:
        trackAngle1 +=2*pi
    trackAngle1=degrees(trackAngle1)    
    vecT2 = __NormalizeVector(end2 - start2)
    trackAngle2 = atan2(vecT2[1],vecT2[0])
    if trackAngle2 > pi:
        trackAngle2 -=2*pi
    if trackAngle2 < -pi:
        trackAngle2 +=2*pi
    trackAngle2=degrees(trackAngle2)
    wxLogDebug('trackAngle1='+str(trackAngle1),dbg)
    wxLogDebug('trackAngle2='+str(trackAngle2),dbg)
    #wxLogDebug('vecT='+str(vecT),dbg)
    
    radius = w1 # via[1]/2.0
    targetLength = w2*(hpercent/100.0) # via[1]*(hpercent/100.0)
    wxLogDebug('targetLength='+str(ToMM(targetLength)),dbg)
    
    if vpercent > 100:
        vpercent = 100
    
    backoff=0
    # choose a teardrop length
    # targetLength = pad.GetSize().x*(hpercent/100.0) # via[1]*(hpercent/100.0)
    n = min(targetLength, track2.GetLength() - backoff)
    consumed = 0

    # if shortened, shrink width too
    if n+consumed < targetLength:
        minVpercent = 100* float(w1) / float(w2)
        vpercent = vpercent*n/targetLength + minVpercent*(1-n/targetLength)

    # find point on the track, sharp end of the teardrop
    pointB = start1 + wxPoint( vecT1[0]*n +vecT1[1]*w1 , vecT1[1]*n -vecT1[0]*w1 )
    pointA = start1 + wxPoint( vecT1[0]*n -vecT1[1]*w1 , vecT1[1]*n +vecT1[0]*w1 )
    # Introduce a last point in order to cover the via centre.
    # If not, the zone won't be filled or not connected
    pointF = start1 + wxPoint( vecT1[0]*n -vecT1[1]*w1 , vecT1[1]*n -vecT1[0] )

    # In some cases of very short, eccentric tracks the points can end up
    # inside the teardrop. If this happens just cancel adding it
    ## if (__PointDistance(pointA, common) < max(w1,w2)  or
    ##     __PointDistance(pointB, common) < max(w1,w2) ):
    ##     wxLogDebug('aborting'+str(targetLength),dbg)
    ##     return False
    # if ( __PointDistance(pointA, via[0]) < radius or
    #      __PointDistance(pointB, via[0]) < radius ):
    #     return False

    # via side points

    # angular positions of where the teardrop meets the via
    dC = asin(vpercent/100.0)
    dE = -dC

    if noBulge:
        # find (signed) angle between track and teardrop
        offAngle = atan2(vecT1[1],vecT1[0]) - atan2(vecT2[1],vecT2[0])
        if offAngle > pi:
            offAngle -=2*pi
        if offAngle < -pi:
            offAngle +=2*pi

        if offAngle+dC > pi/2:
            dC = pi/2 - offAngle

        if offAngle+dE < -pi/2:
            dE = -pi/2 - offAngle
        #wxLogDebug('offAngle='+str(degrees(offAngle)),dbg)
        
    vecC = [vecT2[0]*cos(dC)+vecT2[1]*sin(dC), -vecT2[0]*sin(dC)+vecT2[1]*cos(dC)]
    vecE = [vecT2[0]*cos(dE)+vecT2[1]*sin(dE), -vecT2[0]*sin(dE)+vecT2[1]*cos(dE)]

    pointC = end2 + wxPoint(int(vecC[0] * w2), int(vecC[1] * w2))
    pointE = end2 + wxPoint(int(vecE[0] * w2), int(vecE[1] * w2))
    # pointC = via[0] + wxPoint(int(vecC[0] * radius), int(vecC[1] * radius))
    # pointE = via[0] + wxPoint(int(vecE[0] * radius), int(vecE[1] * radius))

    # Introduce a last point in order to cover the via centre.
    # If not, the zone won't be filled
    pointD = end2 + wxPoint(int(vecT2[0]*-0.15*w2), int(vecT2[1]*-0.15*w2))
    # pointD = via[0] + wxPoint(int(vec[0]*-0.5*radius), int(vec[1]*-0.5*radius))

    pts = [pointA, pointB, pointC, pointD, pointE]
    if segs > 2:
        pts = __ComputeCurvedTracks(vpercent, w1, vecT1, w2, end2, pts, segs)
        #pts = __ComputeCurved(vpercent, w, vecT, via, pts, segs)
        pts = [pointF]+pts
    return pts
##
##
def SetTaper_Zone(pcb=None):
    """Set tapers for track-pad or track-track"""
    if pcb is None:
        pcb = GetBoard()
    selPads = Layout.get_selected_pads()
    selTracks = Layout.get_selected_tracks()
    # taper btw pad & track
    if len(selTracks) == 1 and len(selPads) == 1:
        pad = selPads[0]
        track = selTracks[0]
        segs = 10
        coor = __ComputePoints(track, pad, segs)
        if coor:
            pcb.Add(__Zone(pcb, coor, track))
            RebuildAllZones(pcb)
    elif len(selTracks) == 2 and len(selPads) == 0:
        track1 = selTracks[0]
        track2 = selTracks[1]
        segs = 10
        coor = __ComputePointsTracks(track1, track2, segs)
        if coor:
            pcb.Add(__Zone(pcb, coor, track1))
            RebuildAllZones(pcb)    
    # square taper at the end of a track
    elif len(selTracks) == 1 and len(selPads) == 0:
        track = selTracks[0]
        pnt = track.GetStart()   
        #tracks = Layout.get_tracks_by_pos(pnt)
        # we would need to check the not connected track point
        start = track.GetStart()
        end   = track.GetEnd()        
        for t in pcb.GetTracks():
            if not(t.IsSelected()):
                if track.GetStart() == t.GetStart():
                    start = track.GetEnd()
                    end   = track.GetStart()
                    break
                elif track.GetEnd() == t.GetStart():
                    start = track.GetStart()
                    end   = track.GetEnd()
                    break
                elif track.GetStart() == t.GetEnd():
                    start = track.GetEnd()
                    end   = track.GetStart()
                    break
                elif track.GetEnd() == t.GetEnd():
                    start = track.GetStart()
                    end   = track.GetEnd()
                    break
        w = track.GetWidth()/2
        n = w
        # get normalized track vector
        # it will be used a base vector pointing in the track direction
        vecT = __NormalizeVector(end - start)
        # find point on the track, sharp end of the teardrop
        pointB = start + wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
        pointA = start + wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w )
        pointD = start - wxPoint( vecT[0]*n +vecT[1]*w , vecT[1]*n -vecT[0]*w )
        pointC = start - wxPoint( vecT[0]*n -vecT[1]*w , vecT[1]*n +vecT[0]*w )
        points = [pointA,pointB,pointC,pointD]
        pcb.Add(__Zone(pcb, points, track))       
        RebuildAllZones(pcb)
    else:
        dlg = wx.MessageDialog(None, "Do you want to remove ALL the tapers?",'Taper Remover',wx.OK | wx.CANCEL | wx.ICON_QUESTION | wx.CANCEL_DEFAULT)
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            count = RmTapers()
            wx.LogMessage('Removed '+str(count)+' Tapers')
        else:
            wx.LogMessage('Select:\none Track & one Pad\nor\nTwo Tracks\nor\na single Track')
        dlg.Destroy()
    
##
#
class Layout:
    """
    Class for common Pcbnew layout operations.
    """
    @staticmethod
    def get_selected_pads(board=None):
        if board is None:
            board = pcbnew.GetBoard()
        
        return list(filter(lambda p: p.IsSelected(), board.GetPads()))

    @staticmethod
    def get_selected_tracks(board=None):
        if board is None:
            board = pcbnew.GetBoard()
        
        return list(filter(lambda t: t.IsSelected(), board.GetTracks()))        
    
#
def RebuildAllZones(pcb):
    """Rebuilt all zones"""
    filler = ZONE_FILLER(pcb)
    filler.Fill(pcb.Zones())

#
def __GetAllTapers(board):
    """Just retrieves all teardrops of the current board classified by net"""
    tapers_zones = {}
    for zone in [board.GetArea(i) for i in range(board.GetAreaCount())]:
        if zone.GetPriority() == MAGIC_TAPER_ZONE_ID:
            netname = zone.GetNetname()
            if netname not in tapers_zones.keys():
                tapers_zones[netname] = []
            tapers_zones[netname].append(zone)
    return tapers_zones
#
def RmTapers(pcb=None):
    """Remove all tapers"""

    if pcb is None:
        pcb = GetBoard()

    count = 0
    tapers = __GetAllTapers(pcb)
    for netname in tapers:
        for taper in tapers[netname]:
            pcb.Remove(taper)
            count += 1

    RebuildAllZones(pcb)
    #print('{0} tapers removed'.format(count))
    return count
