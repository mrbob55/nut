#!/usr/bin/python3
# -*- coding: utf-8 -*-
# place this file in your CDNSP directory
# add the following line to the top of your CDNSP.py file:
# from tqdm import tqdm

import argparse
import sys
import os
import re
import pathlib
import urllib3
import json

if not getattr(sys, 'frozen', False):
	os.chdir(os.path.dirname(os.path.abspath(__file__)))

#sys.path.insert(0, 'nut')

from nut import Title
from nut import Titles
from nut import Nsps
import CDNSP
import Fs
from nut import Config
import requests
from nut import Hex
from nut import Print
import threading
import signal
from nut import Status
import time
import colorama
import Server
import pprint
import random
import cdn.Shogun
import cdn.Superfly
import queue
import nut

try:
	from nut import blockchain
except:
	raise

			
def logMissingTitles(file):
	nut.initTitles()
	nut.initFiles()

	f = open(file,"w", encoding="utf-8-sig")
	
	for k,t in Titles.items():
		if t.isUpdateAvailable() and (t.isDLC or t.isUpdate or Config.download.base) and (not t.isDLC or Config.download.DLC) and (not t.isDemo or Config.download.demo) and (not t.isUpdate or Config.download.update) and (t.key or Config.download.sansTitleKey) and (len(Config.titleWhitelist) == 0 or t.id in Config.titleWhitelist) and t.id not in Config.titleBlacklist:
			if not t.id or t.id == '0' * 16 or (t.isUpdate and t.lastestVersion() in [None, '0']):
				continue
			f.write((t.id or ('0'*16)) + '|' + (t.key or ('0'*32)) + '|' + (t.name or '') + "\r\n")
		
	f.close()

def logNcaDeltas(file):
	nut.initTitles()
	nut.initFiles()

	x = open(file,"w", encoding="utf-8-sig")
	
	for k,f in Nsps.files.items():
		try:
			t = f.title()
			if (t.isDLC or t.isUpdate or Config.download.base) and (not t.isDLC or Config.download.DLC) and (not t.isDemo or Config.download.demo) and (not t.isUpdate or Config.download.update) and (t.key or Config.download.sansTitleKey) and (len(Config.titleWhitelist) == 0 or t.id in Config.titleWhitelist) and t.id not in Config.titleBlacklist:
				f.open(f.path)
				if f.hasDeltas():
					Print.info(f.path)
					x.write(f.path + "\r\n")
				f.close()
		except KeyboardInterrupt:
			raise
		except BaseException as e:
			Print.info('error: ' + str(e))
		
	x.close()
	
def updateDb(url, c=0):
	nut.initTitles()

	c += 1

	if c > 3:
		return False

	Print.info("Downloading new title database " + url)
	try:
		if url == '' or not url:
			return
		if "http://" not in url and "https://" not in url:
			try:
				url = base64.b64decode(url)
			except Exception as e:
				Print.info("\nError decoding url: ", e)
				return

		r = requests.get(url)
		r.encoding = 'utf-8-sig'

		if r.status_code == 200:
			try:
				m = re.search(r'<a href="([^"]*)">Proceed</a>', r.text)
				if m:
					return updateDb(m.group(1), c)
			except:
				pass
			Titles.loadTitleBuffer(r.text, False)
		else:
			Print.info('Error updating database: ', repr(r))
			
	except Exception as e:
		Print.info('Error downloading:' + str(e))
		raise

global status
status = None

global scrapeThreads
scrapeThreads = 16

def scrapeThread(id, delta = True):
	size = len(Titles.titles) // scrapeThreads
	st = Status.create(size, 'Thread ' + str(id))
	for i,titleId in enumerate(Titles.titles.keys()):
		try:
			if (i - id) % scrapeThreads == 0:
				Titles.get(titleId).scrape(delta)
				st.add()
		except BaseException as e:
			Print.error(str(e))
	st.close()

global activeDownloads
activeDownloads = []

def downloadThread(i):
	Print.info('starting thread ' + str(i))
	global status
	while Config.isRunning:
		try:
			id = Titles.queue.shift()
			if id and Titles.contains(id):
				activeDownloads[i] = 1
				t = Titles.get(id)
				path = CDNSP.download_game(t.id.lower(), t.lastestVersion(), t.key, True, '', True)

				if os.path.isfile(path):
					nsp = Fs.Nsp(path, None)
					nsp.move()
					Nsps.files[nsp.path] = nsp
					Nsps.save()
					status.add()
				activeDownloads[i] = 0
			else:
				time.sleep(1)
		except KeyboardInterrupt:
			pass
		except BaseException as e:
			Print.error(str(e))
	activeDownloads[i] = 0
	Print.info('ending thread ' + str(i))

global downloadThreadsStarted
downloadThreadsStarted = False

def startDownloadThreads():
	global downloadThreadsStarted
	global activeDownloads

	if downloadThreadsStarted:
		return

	downloadThreadsStarted = True

	nut.initTitles()
	nut.initFiles()

	threads = []
	for i in range(Config.threads):
		activeDownloads.append(0)
		t = threading.Thread(target=downloadThread, args=[i])
		t.daemon = True
		t.start()
		threads.append(t)

def downloadAll(wait = True):
	nut.initTitles()
	nut.initFiles()

	global activeDownloads
	global status

	try:

		for k,t in Titles.items():
			if t.isUpdateAvailable() and (t.isDLC or t.isUpdate or Config.download.base) and (not t.isDLC or Config.download.DLC) and (not t.isDemo or Config.download.demo) and (not t.isUpdate or Config.download.update) and (t.key or Config.download.sansTitleKey) and (len(Config.titleWhitelist) == 0 or t.id in Config.titleWhitelist) and t.id not in Config.titleBlacklist:
				if not t.id or t.id == '0' * 16 or (t.isUpdate and t.lastestVersion() in [None, '0']):
					#Print.warning('no valid id? ' + str(t.path))
					continue
				
				if not t.lastestVersion():
					Print.info('Could not get version for ' + str(t.name) + ' [' + str(t.id) + ']')
					continue

				Titles.queue.add(t.id)
		Titles.save()
		status = Status.create(Titles.queue.size(), 'Total Download')
		startDownloadThreads()
		while wait and (not Titles.queue.empty() or sum(activeDownloads) > 0):
			time.sleep(1)
	except KeyboardInterrupt:
		pass
	except BaseException as e:
		Print.error(str(e))

	if status:
		status.close()

def scanDLC(id, showErr = True, dlcStatus = None):
	id = id.upper()
	title = Titles.get(id)
	baseDlc = Title.baseDlcId(id)
	for i in range(0x1FF):
		scanId = format(baseDlc + i, 'X').zfill(16)
		if Titles.contains(scanId):
			continue
		ver = CDNSP.get_version(scanId.lower())
		if ver != None:
			t = Title()
			t.setId(scanId)
			Titles.set(scanId, t)
			Titles.save()
			Print.info('Found new DLC ' + str(title.name) + ' : ' + scanId)
		elif showErr:
			Print.info('nothing found at ' + scanId + ', ' + str(ver))
		if dlcStatus:
			dlcStatus.add()
	# CDNSP.get_version(args.info.lower())

def scanDLCThread(queue, dlcStatus):
	while queue.size() > 0 and Config.isRunning:
		id = queue.shift()
		if id:
			scanDLC(id, False, dlcStatus)

def startDlcScan(queue):
	dlcStatus = Status.create(queue.size() * 0x200, 'DLC Scan')
	#scanDLC(id)
	threads = []
	for i in range(scrapeThreads):
		t = threading.Thread(target=scanDLCThread, args=[queue, dlcStatus])
		t.start()
		threads.append(t)

	for t in threads:
		t.join()
	dlcStatus.close()

# 0100EBE002B3E000
def getRandomTitleId():
	n = random.randint(0, 0x10000000)
	id = 0x100000000000000
	id += (n & 0xFFFF) << 12
	id += (n & 0xFFF0000) << 20

	return format(id, 'X').zfill(16)

def scanBaseThread(baseStatus):
	while Config.isRunning:
		try:
			id = getRandomTitleId()

			if Titles.contains(id):
				continue

			ver = CDNSP.get_version(id.lower())

			if ver != None:
				Print.info('Found new base ' + id)
				t = Title()
				t.setId(id)
				Titles.set(id, t)
				Titles.save()

			baseStatus.add()
		except BaseException as e:
			print('exception: ' + str(e))

def startBaseScan():
	baseStatus = Status.create(pow(2,28), 'Base Scan')

	threads = []
	for i in range(scrapeThreads):
		t = threading.Thread(target=scanBaseThread, args=[baseStatus])
		t.start()
		threads.append(t)

	for t in threads:
		t.join()

	baseStatus.close()

			
def export(file, cols = ['id', 'rightsId', 'key', 'isUpdate', 'isDLC', 'isDemo', 'baseName', 'name', 'version', 'region']):
	nut.initTitles()
	Titles.export(file, cols)
	
def organize():
	nut.initTitles()
	nut.initFiles()

	#scan()
	Print.info('organizing')
	for k, f in Nsps.files.items():
		#print('moving ' + f.path)
		#Print.info(str(f.hasValidTicket) +' = ' + f.path)
		f.move()

	for id, t in Titles.data().items():
		files = t.getFiles()
		if len(files) > 1:
			#Print.info("%d - %s - %s" % (len(files), t.id, t.name))
			latest = t.getLatestFile()

			if not latest:
				continue

			for f in files:
				if f.path != latest.path:
					f.moveDupe()

	Print.info('removing empty directories')
	Nsps.removeEmptyDir('.', False)
	Nsps.save()
		
def refresh(titleRightsOnly = False):
	nut.initTitles()
	nut.initFiles()
	i = 0
	for k, f in Nsps.files.items():
		try:
			if titleRightsOnly:
				title = Titles.get(f.titleId)
				if title and title.rightsId and (title.key or f.path.endswith('.nsx')):
					continue
			i = i + 1
			print(f.path)
			f.open()
			f.readMeta()
			f.close()

			if i > 20:
				i = 0
				Titles.save()
		except BaseException as e:
			print('exception: ' + str(e))
			pass
	Titles.save()
	
def scanLatestTitleUpdates():
	nut.initTitles()
	nut.initFiles()

	for k,i in CDNSP.get_versionUpdates().items():
		id = str(k).upper()
		version = str(i)
		
		if not Titles.contains(id):
			if len(id) != 16:
				Print.info('invalid title id: ' + id)
				continue
			continue
			t = Title()
			t.setId(id)
			Titles.set(id, t)
			Print.info('Found new title id: ' + str(id))
			
		t = Titles.get(id)
		if str(t.version) != str(version):
			Print.info('new version detected for %s[%s] v%s' % (t.name or '', t.id or ('0' * 16), str(version)))
			t.setVersion(version, True)
			
	Titles.save()
	
def updateVersions(force = True):
	nut.initTitles()
	nut.initFiles()

	i = 0
	for k,t in Titles.items():
		if force or t.version == None:
			if (t.isDLC or t.isUpdate or Config.download.base) and (not t.isDLC or Config.download.DLC) and (not t.isDemo or Config.download.demo) and (not t.isUpdate or Config.download.update) and (t.key or Config.download.sansTitleKey) and (len(Config.titleWhitelist) == 0 or t.id in Config.titleWhitelist) and t.id not in Config.titleBlacklist:
				v = t.lastestVersion(True)
				Print.info("%s[%s] v = %s" % (str(t.name), str(t.id), str(v)) )
			
				i = i + 1
				if i % 20 == 0:
					Titles.save()
			
	for t in list(Titles.data().values()):
		if not t.isUpdate and not t.isDLC and t.updateId and t.updateId and not Titles.contains(t.updateId):
			u = Title()
			u.setId(t.updateId)
			
			if u.lastestVersion():
				Titles.set(t.updateId, u)
				
				Print.info("%s[%s] FOUND" % (str(t.name), str(u.id)) )
				
				i = i + 1
				if i % 20 == 0:
					Titles.save()
					
	Titles.save()


def unlockAll():
	nut.initTitles()
	nut.initFiles()

	for k,f in Nsps.files.items():
		if f.isUnlockable():
			try:
				if not blockchain.verifyKey(f.titleId, f.title().key):
					raise IOError('Could not verify title key! %s / %s - %s' % (f.titleId, f.title().key, f.title().name))
					continue
				Print.info('unlocking ' + f.path)
				f.open(f.path, 'r+b')
				f.unlock()
				f.close()
			except BaseException as e:
				Print.info('error unlocking: ' + str(e))

def exportVerifiedKeys(fileName):
	nut.initTitles()
	with open(fileName, 'w') as f:
		f.write('id|key|version\n')
		for tid,key in blockchain.blockchain.export().items():
			title = Titles.get(tid)
			if title and title.rightsId:
				f.write(str(title.rightsId) + '|' + str(key) + '|' + str(title.version) + '\n')
				
def exportKeys(fileName):
	nut.initTitles()
	with open(fileName, 'w') as f:
		f.write('id|key|version\n')
		for tid,title in Titles.items():
			if title and title.rightsId and title.key and title.isActive():
				f.write(str(title.rightsId) + '|' + str(title.key) + '|' + str(title.version) + '\n')

def submitKeys():
	for id, t in Titles.items():
		if t.key and len(t.getFiles()) > 0:
			try:
				#blockchain.blockchain.suggest(t.id, t.key)
				if not blockchain.verifyKey(t.id, t.key):
					Print.error('Key verification failed for %s / %s' % (str(t.id), str(t.key)))
					for f in t.getFiles():
						f.hasValidTicket = False
						f.move()
			except LookupError as e:
				Print.info(str(e))
			except OSError as e:
				Print.info(str(e))
			except BaseException as e:
				Print.info(str(e))
				raise



def scrapeShogun():
	nut.initTitles()
	nut.initFiles()

	for region in cdn.regions():				
		cdn.Shogun.scrapeTitles(region)
	Titles.saveAll()


def scrapeShogunWorker(q):
	while True:
		region = q.get()

		if region is None:
			break

		cdn.Shogun.scrapeTitles(region)

		q.task_done()

def scrapeShogunThreaded():
	nut.initTitles()
	nut.initFiles()

	scrapeThreads = []
	numThreads = 8

	q = queue.Queue()

	for region in cdn.regions():
		q.put(region)

	for i in range(numThreads):
		t = threading.Thread(target=scrapeShogunWorker, args=[q])
		t.daemon = True
		t.start()
		scrapeThreads.append(t)

	q.join()

	for i in range(numThreads):
		q.put(None)

	for t in scrapeThreads:
		t.join()
	Titles.saveAll()

def genTinfoilTitles():
	nut.initTitles()
	nut.initFiles()

	for region, languages in Config.regionLanguages().items():			
		for language in languages:
			nut.importRegion(region, language)
			Titles.save('titledb/titles.%s.%s.json' % (region, language), False)
			#Print.info('%s - %s' % (region, language))
	scanLatestTitleUpdates()
	export('titledb/versions.txt', ['rightsId', 'version'])

def download(id):
	bits = id.split(',')

	version = None
	key = None

	if len(bits) == 1:
		id = bits[0].upper()
	elif len(bits) == 2:
		id = bits[0].upper()
		key = bits[1].strip()
	elif len(bits) == 3:
		id = bits[0].upper()
		key = bits[1].strip()
		version = bits[2].strip()
	else:
		Print.info('invalid args: ' + download)
		return False

	if key == '':
		key = None

	if version == '':
		version = None

	if len(id) != 16:
		raise IOError('Invalid title id format')

	if Titles.contains(id):
		title = Titles.get(id)

		if version == None:
			version = title.lastestVersion()

		if version == None:
			if not title.key:
				Titles.erase(id)
			return False

		CDNSP.download_game(title.id.lower(), version or title.lastestVersion(), key or title.key, True, '', True)
	else:
		CDNSP.download_game(id.lower(), version or CDNSP.get_version(id.lower()), key, True, '', True)
	return True

def matchDemos():
	for nsuId, rt in Titles.data('US', 'en'):
		if rt.id:
			continue

		for tid, t in Titles.data():
			if rt.name.startsWith(t.name) or (t.name == rt.name and len(t.name) > 5):
				print(rt.name + ' - ' + t.name)
				break


def organizeNcas(dir):
	files = [f for f in os.listdir(dir) if f.endswith('.nca')]
	
	for file in files:
		try:
			path = os.path.join(dir, file)
			f = Fs.Nca()
			f.open(path, 'r+b')
			f.close()
			titleId = f.header.titleId
			header = f.header
			os.makedirs(os.path.join(dir, f.header.titleId), exist_ok=True)

			dest = os.path.join(dir, f.header.titleId, file)
			os.rename(path, dest)
			Print.info(dest)
		except BaseException as e:
			Print.info(str(e))

			
if __name__ == '__main__':
	try:
		urllib3.disable_warnings()

		#signal.signal(signal.SIGINT, handler)


		CDNSP.tqdmProgBar = False


		CDNSP.hactoolPath = Config.paths.hactool
		CDNSP.keysPath = Config.paths.keys
		CDNSP.NXclientPath = Config.paths.NXclientCert
		CDNSP.ShopNPath = Config.paths.shopNCert
		CDNSP.reg = Config.cdn.region
		CDNSP.fw = Config.cdn.firmware
		CDNSP.deviceId = Config.cdn.deviceId
		CDNSP.env = Config.cdn.environment
		CDNSP.dbURL = 'titles.txt'
		CDNSP.nspout = Config.paths.nspOut


		if CDNSP.keysPath != '':
			CDNSP.keysArg = ' -k "%s"' % CDNSP.keysPath
		else:
			CDNSP.keysArg = ''


		parser = argparse.ArgumentParser()
		parser.add_argument('file',nargs='*')
		parser.add_argument('--base', type=int, choices=[0, 1], default=Config.download.base*1, help='download base titles')
		parser.add_argument('--demo', type=int, choices=[0, 1], default=Config.download.demo*1, help='download demo titles')
		parser.add_argument('--update', type=int, choices=[0, 1], default=Config.download.update*1, help='download title updates')
		parser.add_argument('--dlc', type=int, choices=[0, 1], default=Config.download.DLC*1, help='download DLC titles')
		parser.add_argument('--nsx', type=int, choices=[0, 1], default=Config.download.sansTitleKey*1, help='download titles without the title key')
		parser.add_argument('-D', '--download-all', action="store_true", help='download ALL title(s)')
		parser.add_argument('-d', '--download', nargs='+', help='download title(s)')
		parser.add_argument('-i', '--info', help='show info about title or file')
		parser.add_argument('--depth', type=int, default=1, help='max depth for file info and extraction')
		parser.add_argument('-I', '--verify', nargs=2, help='verify title key TID TKEY')
		parser.add_argument('-u', '--unlock', help='install available title key into NSX / NSP')
		parser.add_argument('--unlock-all', action="store_true", help='install available title keys into all NSX files')
		parser.add_argument('--set-masterkey1', help='Changes the master key encryption for NSP.')
		parser.add_argument('--set-masterkey2', help='Changes the master key encryption for NSP.')
		parser.add_argument('--set-masterkey3', help='Changes the master key encryption for NSP.')
		parser.add_argument('--set-masterkey4', help='Changes the master key encryption for NSP.')
		parser.add_argument('--set-masterkey5', help='Changes the master key encryption for NSP.')
		parser.add_argument('--remove-title-rights', nargs='+', help='Removes title rights encryption from all NCA\'s in the NSP.')
		parser.add_argument('-s', '--scan', action="store_true", help='scan for new NSP files')
		parser.add_argument('-Z', action="store_true", help='update ALL title versions from nintendo')
		parser.add_argument('-z', action="store_true", help='update newest title versions from nintendo')
		parser.add_argument('-V', action="store_true", help='scan latest title updates from nintendo')
		parser.add_argument('-o', '--organize', action="store_true", help='rename and move all NSP files')
		parser.add_argument('-U', '--update-titles', action="store_true", help='update titles db from urls')
		parser.add_argument('-r', '--refresh', action="store_true", help='reads all meta from NSP files and queries CDN for latest version information')
		parser.add_argument('-R', '--read-rightsids', action="store_true", help='reads all title rights ids from nsps')
		parser.add_argument('-x', '--extract', nargs='+', help='extract / unpack a NSP')
		parser.add_argument('-c', '--create', help='create / pack a NSP')
		parser.add_argument('-e', '--seteshop', help='Set NSP NCA''s as eshop')
		parser.add_argument('--export', help='export title database in csv format')
		parser.add_argument('--export-versions', help='export title version database in csv format')
		parser.add_argument('-M', '--missing', help='export title database of titles you have not downloaded in csv format')
		parser.add_argument('--nca-deltas', help='export list of NSPs containing delta updates')
		parser.add_argument('--silent', action="store_true", help='Suppress stdout/stderr output')
		parser.add_argument('--json', action="store_true", help='JSON output')
		parser.add_argument('--usb', action="store_true", help='Run usb daemon')
		parser.add_argument('-S', '--server', action="store_true", help='Run server daemon')
		parser.add_argument('-m', '--hostname', help='Set server hostname')
		parser.add_argument('-p', '--port', type=int, help='Set server port')
		parser.add_argument('-b', '--blockchain', action="store_true", help='run blockchain server')
		parser.add_argument('-k', '--submit-keys', action="store_true", help='Submit all title keys to blockchain')
		parser.add_argument('-K', '--export-verified-keys', help='Exports verified title keys from blockchain')
		parser.add_argument('--export-keys', help='Exports title keys from blockchain')

		parser.add_argument('--scrape', action="store_true", help='Scrape ALL titles from Nintendo servers')
		parser.add_argument('--scrape-delta', action="store_true", help='Scrape ALL titles from Nintendo servers that have not been scraped yet')
		parser.add_argument('--scrape-title', help='Scrape title from Nintendo servers')

		parser.add_argument('--scrape-shogun', nargs='*', help='Scrape ALL titles from shogun')
		parser.add_argument('--scrape-languages', action="store_true", help='Scrape languages from shogun')

		parser.add_argument('--refresh-regions', action="store_true", help='Refreshes the region and language mappings in Nut\'s DB')
		parser.add_argument('--import-region', help='Localizes Nut\'s DB to the specified region')
		parser.add_argument('--language', help='Specify language to be used with region')

		parser.add_argument('--scan-base', nargs='*', help='Scan for new base Title ID\'s')
		parser.add_argument('--scan-dlc', nargs='*', help='Scan for new DLC Title ID\'s')

		parser.add_argument('--match-demos', action="store_true", help='Try to fuzzy match demo tids to nsuIds')

		parser.add_argument('--gen-tinfoil-titles', action="store_true", help='Outputs language files for Tinfoil')
		parser.add_argument('-O', '--organize-ncas', help='Organize unsorted NCA\'s')

		
		args = parser.parse_args()

		Config.download.base = bool(args.base)
		Config.download.DLC = bool(args.dlc)
		Config.download.demo = bool(args.demo)
		Config.download.sansTitleKey = bool(args.nsx)
		Config.download.update = bool(args.update)

		if args.hostname:
			args.server = True
			Config.server.hostname = args.hostname

		if args.port:
			args.server = True
			Config.server.port = int(args.port)

		if args.silent:
			Print.silent = True

		if args.json:
			Config.jsonOutput = True

		Status.start()


		Print.info('                        ,;:;;,')
		Print.info('                       ;;;;;')
		Print.info('               .=\',    ;:;;:,')
		Print.info('              /_\', "=. \';:;:;')
		Print.info('              @=:__,  \,;:;:\'')
		Print.info('                _(\.=  ;:;;\'')
		Print.info('               `"_(  _/="`')
		Print.info('                `"\'')

		if args.extract:
			nut.initTitles()
			for filePath in args.extract:
				#f = Fs.Nsp(filePath, 'rb')
				f = Fs.factory(filePath)
				f.open(filePath, 'rb')
				dir = os.path.splitext(os.path.basename(filePath))[0]
				f.unpack(dir)
				f.close()

		if args.create:
			Print.info('creating ' + args.create)
			nsp = Fs.Nsp(None, None)
			nsp.path = args.create
			nsp.pack(args.file)
			#for filePath in args.file:
			#	Print.info(filePath)

	
		if args.update_titles:
			nut.initTitles()
			for url in Config.titleUrls:
				updateDb(url)
			Titles.loadTxtDatabases()
			Titles.save()

		if args.submit_keys:
			nut.initTitles()
			nut.initFiles()
			submitKeys()

		if args.seteshop:
			#nut.initTitles()
			#nut.initFiles()
			f = Fs.factory(args.seteshop)
			f.open(args.seteshop, 'r+b')
			f.setGameCard(False)
			f.close()

		if args.scrape_languages:
			cdn.Shogun.saveLanguages()
			exit(0)

		if args.refresh_regions:
			nut.refreshRegions()
			exit(0)

		if args.import_region:
			region = args.import_region.upper()
			if not args.language:
				args.language = Config.language

			args.language = args.language.lower()

			nut.importRegion(region, args.language)
			exit(0)

		if args.usb:
			try:
				import Usb
			except BaseException as e:
				Print.error('pip3 install pyusb, required for USB coms: ' + str(e))
			nut.scan()
			Usb.daemon()
		
		if args.download:
			nut.initTitles()
			nut.initFiles()
			for d in args.download:
				download(d)
	
		if args.scan:
			nut.initTitles()
			nut.initFiles()
			nut.scan()
		
		if args.refresh:
			nut.initTitles()
			nut.initFiles()
			refresh(False)
			
		if args.read_rightsids:
			nut.initTitles()
			nut.initFiles()
			refresh(True)
	
		if args.organize:
			nut.initTitles()
			nut.initFiles()
			organize()

		if args.set_masterkey1:
			nut.initTitles()
			nut.initFiles()
			f = Fs.Nsp(args.set_masterkey1, 'r+b')
			f.setMasterKeyRev(0)
			f.flush()
			f.close()
			pass

		if args.set_masterkey2:
			nut.initTitles()
			nut.initFiles()
			f = Fs.Nsp(args.set_masterkey2, 'r+b')
			f.setMasterKeyRev(2)
			f.flush()
			f.close()
			pass

		if args.set_masterkey3:
			nut.initTitles()
			nut.initFiles()
			f = Fs.Nsp(args.set_masterkey3, 'r+b')
			f.setMasterKeyRev(3)
			f.flush()
			f.close()
			pass

		if args.set_masterkey4:
			nut.initTitles()
			nut.initFiles()
			f = Fs.Nsp(args.set_masterkey4, 'r+b')
			f.setMasterKeyRev(4)
			f.flush()
			f.close()
			pass

		if args.set_masterkey5:
			nut.initTitles()
			nut.initFiles()
			f = Fs.Nsp(args.set_masterkey5, 'r+b')
			f.setMasterKeyRev(5)
			f.flush()
			f.close()
			pass

		if args.remove_title_rights:
			nut.initTitles()
			nut.initFiles()
			for fileName in args.remove_title_rights:
				try:
					f = Fs.Nsp(fileName, 'r+b')
					f.removeTitleRights()
					f.flush()
					f.close()
				except BaseException as e:
					Print.error('Exception: ' + str(e))

		if args.nca_deltas:
			logNcaDeltas(args.nca_deltas)

		if args.verify:
			if blockchain.verifyKey(args.verify[0], args.verify[1]):
				Print.info('Title key is valid')
			else:
				Print.info('Title key is INVALID %s - %s' % (args.verify[0], args.verify[1]))

		if args.info:
			nut.initTitles()
			nut.initFiles()
			if re.search(r'^[A-Fa-f0-9]+$', args.info.strip(), re.I | re.M | re.S):
				Print.info('%s version = %s' % (args.info.upper(), CDNSP.get_version(args.info.lower())))
			else:
				print('reading')
				f = Fs.factory(args.info)
				f.open(args.info, 'r+b')
				f.printInfo(args.depth+1)
				'''
				for i in f.cnmt():
					for j in i:
						Print.info(j._path)
						j.rewind()
						buf = j.read()
						Hex.dump(buf)
						j.seek(0x28)
						#j.writeInt64(0)
						Print.info('min: ' + str(j.readInt64()))
				#f.flush()
				#f.close()
				'''

		if args.scrape_shogun != None:
			if len(args.scrape_shogun) == 0:
				scrapeShogunThreaded()
			else:
				nut.initTitles()
				nut.initFiles()
				for i in args.scrape_shogun:
					if len(i) == 16:
						l = cdn.Shogun.ids(i)
						if not l or len(l) == 0 or len(l['id_pairs']) == 0:
							print('no nsuId\'s found')
						else:
							print(l)
							for t in l['id_pairs']:
								print('nsuId: ' + str(t['id']))
								print(json.dumps(cdn.Shogun.scrapeTitle(t['id']).__dict__))
								Titles.saveRegion('US', 'en')
					else:
						print('bleh')

		if args.gen_tinfoil_titles:
			genTinfoilTitles()

		if args.scrape_title:
			nut.initTitles()
			nut.initFiles()

			if not Titles.contains(args.scrape_title):
				Print.error('Could not find title ' + args.scrape_title)
			else:
				Titles.get(args.scrape_title).scrape(False)
				Titles.save()
				#Print.info(repr(Titles.get(args.scrape_title).__dict__))
				pprint.pprint(Titles.get(args.scrape_title).__dict__)

		if args.scrape or args.scrape_delta:
			nut.initTitles()
			nut.initFiles()

			threads = []
			for i in range(scrapeThreads):
				t = threading.Thread(target=scrapeThread, args=[i, args.scrape_delta])
				t.start()
				threads.append(t)

			for t in threads:
				t.join()
		
			Titles.save()
			
	
		if args.Z:
			updateVersions(True)
		
		if args.z:
			updateVersions(False)
		
		if args.V:
			scanLatestTitleUpdates()

		if args.unlock_all:
			unlockAll()
			pass

		if args.unlock:
			nut.initTitles()
			nut.initFiles()
			Print.info('opening ' + args.unlock)
			f = Fs.Nsp(args.unlock, 'r+b')
			f.unlock()


		
		if args.download_all:
			downloadAll()
			Titles.save()
		
		if args.export:
			nut.initTitles()
			nut.initFiles()
			export(args.export)

		if args.export_versions:
			nut.initTitles()
			nut.initFiles()
			export(args.export_versions, ['rightsId', 'version'])
		
		if args.missing:
			logMissingTitles(args.missing)

		if args.match_demos:
			matchDemos()

		if args.server:
			startDownloadThreads()
			nut.initTitles()
			nut.initFiles()
			Server.run()

		if args.blockchain:
			nut.initTitles()
			nut.initFiles()
			try:
				import blockchain
			except:
				pass
			blockchain.run()
		
		if len(sys.argv)==1:
			nut.scan()
			organize()
			downloadAll()
			scanLatestTitleUpdates()
			export('titledb/versions.txt', ['rightsId', 'version'])

		if args.scan_dlc != None:
			nut.initTitles()
			nut.initFiles()
			queue = Titles.Queue()
			if len(args.scan_dlc) > 0:
				for id in args.scan_dlc:
					queue.add(id)
			else:
				for i,k in Titles.items():
					if not k.isDLC and not k.isUpdate and k.id:
						queue.add(k.id)
			startDlcScan(queue)

		if args.scan_base != None:
			nut.initTitles()
			nut.initFiles()
			startBaseScan()

		if args.export_verified_keys:
			exportVerifiedKeys(args.export_verified_keys)
			
		if args.export_keys:
			exportKeys(args.export_keys)

		if args.organize_ncas:
			organizeNcas(args.organize_ncas)

		Status.close()
	

	except KeyboardInterrupt:
		Config.isRunning = False
		Status.close()
	except BaseException as e:
		Config.isRunning = False
		Status.close()
		raise

	Print.info('fin')

