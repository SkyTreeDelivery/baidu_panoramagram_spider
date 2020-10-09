import requests as re
import psycopg2
from po.DataGroup import DataGroup
from po.PanoCur import PanoCur
from po.RoadFragment import RoadFragment
from po.RoadFragmentTopo import RoadFragmentTopo
import uuid
from po.GroupHistory import GroupHistory
from po.PanoHistory import PanoHistory
import time


headers = {
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36'
}

from enum import Enum
class PanoType(Enum):
    START = 0
    End = 1
    MIDDLE = 2

# def(panoid,level):

# 获得数据库连接
def getConn():
    return psycopg2.connect(database="postgres", user="postgres", password="zhang002508", host="localhost", port="5432")

def getDataGroupByPanoId(panoid):
    request2 = getRequestResult(panoid)
    return request2ToDataGroup(request2)

# 获得请求数据
def getRequestResult(panoid):
    request2 = re.get('https://mapsv0.bdimg.com',params={
    'qt':'sdata',
    'sid':panoid
    },headers=headers)
    return request2

# 将request 2 的结果进行结构化处理
def request2ToDataGroup(request):
    dataGroup = DataGroup()

    json = request.json()
    infoJson = json['content'][0]
    panoid = infoJson['ID']
    date = infoJson['Date']
    heading = infoJson['Heading']
    pitch = infoJson['Pitch']
    links = infoJson['Links']
    roads = infoJson['Roads']
    currentroads = roads[0]
    roadId = currentroads['ID']
    roadName = currentroads['Name']
    panos = currentroads['Panos']
    timeLine = infoJson['TimeLine']

    pano_cur = PanoCur(panoid)
    pano_cur.pid = panoid
    pano_cur.time = date
    pano_cur.heading = heading
    pano_cur.pitch = pitch
    pano_cur.rid = roadId
    curIndex = getPanoIndex(panoid,panos) # 获得当前点在路段数据中的下标
    dataGroup.panoCurIndex = curIndex
    if(curIndex == 0):
        dataGroup.locType = PanoType.START
    elif(curIndex == len(panos) - 1):
        dataGroup.locType = PanoType.End
    else:
        dataGroup.locType = PanoType.MIDDLE

    # 处理pano数据
    panoObjs = []
    line = [] # 路段数据
    for i in range(len(panos)):
        pano = panos[i]
        panoObj = None
        if(i != curIndex):
            panoObj = parsePano(pano)
            panoObj.rid = roadId
            line.append([panoObj.x,panoObj.y])
            panoObjs.append(panoObj)
        else:
            panoObj = parsePano(pano,pano_cur)
            line.append([panoObj.x,panoObj.y])
            panoObjs.append(panoObj)
        # 判断是否为端点
        if(i == 0 or i == len(panos) - 1):
            panoObj.isendpoint = True

    dataGroup.panos = panoObjs
    # 处理道路数据
    roadObj = RoadFragment()
    roadObj.rid = roadId
    roadObj.name = roadName
    roadObj.from_pid = panos[0]['PID']
    roadObj.to_pid = panos[len(panos) - 1]["PID"]
    roadObj.line = line
    dataGroup.roadFragment = roadObj

    # 处理历史数据
    # 历史组
    groupHistory = GroupHistory()
    groupHistory.gid = uuid.uuid4().hex
    groupHistory.count = len(timeLine)
    groupHistory.currentTime = date
    groupHistory.currentPid = panoid
    dataGroup.hisGroup = groupHistory
    for pano in dataGroup.panos:
        pano.timeGroupId = groupHistory.gid
    # timeline
    panosHis = []
    for i in range(1,len(timeLine)):
        panoHis = timeLine[i]
        panoHisObj = parsePanoHis(panoHis,groupHistory.gid)
        panosHis.append(panoHisObj)
    dataGroup.panosHistory = panosHis

    # 处理道路拓扑
    linkObjs = []
    linkSize = len(links)
    if(linkSize != 0):
        for i in range(linkSize):
            link = links[i]
            linkObj = RoadFragmentTopo()
            linkObj.tid = uuid.uuid4().hex
             # 生成随机id
            linkObj.pid1 = panoid
            linkObj.rid1 = roadId
            linkObj.pid2 = link['PID']
            linkObj.rid2 = link['RID']
            linkObjs.append(linkObj)
        if(linkSize >= 2): # 说明出现了节点Node
            dataGroup.panos[curIndex].isnode = True
    else:
        # 筛选出道路的尽头，视为node
        if(curIndex == 0 or curIndex == len(panos) - 1):
            dataGroup.panos[curIndex].isnode = True

    dataGroup.topo = linkObjs
    return dataGroup


def parsePano(pano,panoObj = None):
    order = pano['Order']
    pid = pano['PID']
    ptype = pano['Type']
    x = pano['X']
    y = pano['Y']

    if(panoObj == None):
        panoObj =  PanoCur(pid)
    panoObj.pid = pid
    panoObj.order = order
    panoObj.type = ptype
    panoObj.x = x
    panoObj.y = y
    return panoObj

def parsePanoHis(panoHis,timeGroupId):
    pid = panoHis['ID']
    time = panoHis['TimeLine']
    panoHisObj = PanoHistory(pid)
    panoHisObj.time = time
    panoHisObj.time_group_id = timeGroupId
    return panoHisObj

def getPanoType(panoid,panos):
    ptype = PanoType.START
    if(panos[0]['PID'] == panoid):
        ptype = PanoType.START
    elif(panos[len(panos) - 1]['PID'] == panoid):
        ptype = PanoType.End
    else:
        ptype = PanoType.MIDDLE
    return ptype

def getPanoIndex(panoid,panos):
    for i in range(len(panos)):
        if(panoid == panos[i]['PID']):
            return i
        return -1

# --------------------------------   DAO   --------------------------------------------------------
# 插入非当前请求点的同路段的其他点
def insertPano_simple(pano):
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''INSERT INTO public.pano_current(
	pid, rid, geom, type, time_group_id, isnode, "order", isendpoint)
	VALUES (%s ,%s, ST_GeomFromText('POINT(%s %s)',4326),  %s, %s, %s ,%s, %s);'''
    ,(pano.pid,pano.rid,pano.x,pano.y ,pano.type,pano.timeGroupId,
    pano.isnode, pano.order,pano.isendpoint))

    conn.commit()
    conn.close()
    recordPano(pano.pid)
    showProcess()


def insertPano(pano):
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''INSERT INTO public.pano_current(
	pid, rid, geom, "time", heading, pitch, type, isnode,time_group_id, "order",isendpoint)
	VALUES (%s, %s,ST_GeomFromText('POINT(%s %s)',4326), %s, %s, %s, %s, %s, %s,%s, %s);'''
    ,(pano.pid,pano.rid,pano.x,pano.y,pano.time,pano.heading,pano.pitch
            ,pano.type,pano.isnode, pano.timeGroupId,pano.order,pano.isendpoint))

    conn.commit()
    conn.close()
    recordPano(pano.pid)
    showProcess()


def insertPanoHis(pid,time,time_group_id):
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''INSERT INTO public.pano_history(
	pid, "time", time_group_id)
	VALUES (%s, %s, %s);''',(pid,time,time_group_id))

    conn.commit()
    conn.close()

def insertGroupHistory(gid, count, current_time, current_pid):
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''INSERT INTO public.group_history(
	gid, count, "current_time", current_pid)
	VALUES (%s, %s, %s, %s);''',(gid, count, current_time, current_pid))

    conn.commit()
    conn.close()

def insertRoadFragment(rid, from_pid, to_pid, line, name):
    conn = getConn()
    strlist = map(lambda x: '{0} {1}'.format(x[0], x[1]) , line)
    wktLineString = ','.join(strlist)
    if(len(line) != 1):
        wktLineString = 'LINESTRING({0})'.format(wktLineString)
    else:
        wktLineString = 'LINESTRING({0},{0})'.format(wktLineString)
    
    cur = conn.cursor()
    cur.execute('''INSERT INTO public.road_fragment(
	rid, from_pid, to_pid, geom, name)
	VALUES (%s, %s, %s, ST_GeomFromText(%s,4326), %s);''',(rid, from_pid, to_pid, wktLineString, name))

    conn.commit()
    conn.close()

    recordRoad(rid)

def insertTopo(tid, pid1, pid2, rid1, rid2):
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''INSERT INTO public.road_fragment_topo(
	tid, pid1, pid2, rid1, rid2)
	VALUES (%s, %s, %s, %s, %s);''',(tid, pid1, pid2, rid1, rid2))

    conn.commit()
    conn.close()
    recordTopo(pid1,pid2)

def listPanos():
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''SELECT pid FROM public.pano_current''')
    records = cur.fetchall()

    conn.close()
    return records
def listTopos():
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''SELECT pid1, pid2 FROM public.road_fragment_topo''')
    records = cur.fetchall()

    conn.close()
    return records

def listRoads():
    conn = getConn()

    cur = conn.cursor()
    cur.execute('''SELECT rid FROM public.road_fragment;''')
    records = cur.fetchall()

    conn.close()
    return records

# ------------- service -----------------------------
def savePanos(panos,curIndex):
    for i in range(len(panos)):
        pano = panos[i]
        if(pano.pid in panomap.keys()): # 假设已经把保存过
            return False
        if(i == curIndex): # 插入当前点（相较于其他点，多了heading，pitch，time等信息
            insertPano(pano)  
        else:
            insertPano_simple(pano)
    return True

def saveRoad(road):
    if(road.rid in roadmap.keys()):
        return False
    insertRoadFragment(road.rid,road.from_pid,road.to_pid,road.line,road.name)
    return True

def saveLinks(links):
    for topo in links:
        key = '{0} - {1}'.format(topo.pid1,topo.pid2)
        # if(key in topomap.keys()):
        #     return False
        insertTopo(topo.tid,topo.pid1,topo.pid2,topo.rid1,topo.rid2)
    return True

def saveHisGroup(hisGroup):
    insertGroupHistory(hisGroup.gid,hisGroup.count,hisGroup.currentTime,hisGroup.currentPid)


# ---------------  main  ----------------------------
def requestPano(current_panoid):
    
    dataGroup = getDataGroupByPanoId(current_panoid)

    if(dataGroup.locType == PanoType.MIDDLE):
        # 保存panos
        panos = dataGroup.panos
        fp = savePanos(panos,dataGroup.panoCurIndex)
        fr = saveRoad(dataGroup.roadFragment) # 保存道路
        
        # 获得link数据
        startPanoDataGroup = getDataGroupByPanoId(panos[0].pid)
        endPanoDataGroup = getDataGroupByPanoId(panos[len(panos) - 1].pid)

        # 保存道路拓扑
        fl1 = saveLinks(startPanoDataGroup.topo)
        fl2 = saveLinks(endPanoDataGroup.topo)

        # 保存历史组数据,暂不处理历史点数据
        saveHisGroup(dataGroup.hisGroup)

        if(not(fp and fr and fl1 and fl2)):
            return 0
        # 加入队列
        for link in startPanoDataGroup.topo:
            queue.append(link.pid2)
        for link in endPanoDataGroup.topo:
            queue.append(link.pid2)

    elif(dataGroup.locType == PanoType.START):
         # 保存panos
        panos = dataGroup.panos
        fp = savePanos(panos,dataGroup.panoCurIndex)
        fr = saveRoad(dataGroup.roadFragment) # 保存道路

        endPanoDataGroup = getDataGroupByPanoId(panos[len(panos) - 1].pid)
        fl = saveLinks(endPanoDataGroup.topo)
        saveHisGroup(dataGroup.hisGroup)

        if(not(fp and fr and fl)):
            return 0
        # 加入队列
        for link in endPanoDataGroup.topo:
            queue.append(link.pid2)

    else:
         # 保存panos
        panos = dataGroup.panos
        fp = savePanos(panos,dataGroup.panoCurIndex)
        fr = saveRoad(dataGroup.roadFragment) # 保存道路

        startPanoDataGroup = getDataGroupByPanoId(panos[0].pid)
        fl = saveLinks(startPanoDataGroup.topo)
        saveHisGroup(dataGroup.hisGroup)

        if(not(fp and fr and fl)):
            return 0
        # 加入队列
        for link in startPanoDataGroup.topo:
            queue.append(link.pid2)

# 队列调度程序，采用广度优先策略
def dispatch(pid):
    requestPano(pid)
    while len(queue) != 0:
        requestPano(queue[0])
        queue.pop(0) # 移出队列


# 记录并每隔100条展示进度
def showProcess():
    if(record['panoCount'] % 100 == 0):
        print(''' {0} -- pano \n
                  {1} -- road,\n
                  {2} -- topo \n
                  --------------  '''
                  .format(record['panoCount'],record['roadCount'],record['topoCount']))

def recordPano(pid):
    panomap[pid] = 1 # 插入记录
    record['panoCount'] += 1

def recordRoad(rid):
    roadmap[rid] = 1
    record['roadCount'] += 1

def recordTopo(pid1,pid2):
    topomap['{0} - {1}'.format(pid1,pid2)] = 1
    topomap['{1} - {0}'.format(pid1,pid2)] = 1
    record['topoCount'] += 1


def initMap():
    # 初始化panomap
    panoRecords = listPanos()
    for record in panoRecords:
        panomap[record[0]] = 1

    # 初始化roadmap
    roadRecords = listRoads()
    for record in roadRecords:
        roadmap[record[0]] = 1

    #初始化topomap
    topoRecords = listTopos()
    for record in topoRecords:
        topomap['{0} - {1}'.format(record[0],record[1])] = 1
        topomap['{1} - {0}'.format(record[0],record[1])] = 1

# 已经采集的pano记录
panomap={}
roadmap={}
topomap={}
record={
    'panoCount':0,
    'roadCount':0,
    'topoCount':0
}

# 入口函数
def main():
    # 初始化记录容器
    initMap()

    # 执行爬取程序
    initPid = '09000200121905051402166819P'
    # requestPano(initPid) 
    dispatch(initPid)

queue=[]

main()