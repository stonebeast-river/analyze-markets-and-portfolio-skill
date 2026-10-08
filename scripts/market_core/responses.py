"""Private immutable HTTP receipts with integrity-checked, time-bounded cache pointers."""
import gzip
import hashlib
import json
import io
import os
import time
import uuid
import zlib
from datetime import datetime,timezone
from pathlib import Path


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode('utf-8')


class ResponseVault:
    def __init__(self,directory):
        self.directory=Path(directory).resolve();self.events=[]

    @staticmethod
    def request_id(url,headers):
        # Include credentials in the one-way namespace, never in written metadata.
        return hashlib.sha256(encoded({'url':url,'headers':dict(sorted(headers.items()))})).hexdigest()

    def _path(self,relative):
        path=(self.directory/relative).resolve()
        if self.directory not in path.parents:raise ValueError('Response receipt path leaves archive')
        return path

    @staticmethod
    def verify_reference(reference):
        """Verify a row's immutable receipt metadata and both archived byte streams."""
        vault = ResponseVault(reference['archive_directory'])
        data = vault._path(reference['receipt_path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != reference['receipt_sha256']:
            raise ValueError('Source receipt metadata hash mismatch')
        record = json.loads(data)
        if record.get('status') != 'http_ok' or record.get('http_status') != 200:
            raise ValueError('Row references an unsuccessful HTTP response')
        for key in ('request_id', 'request_url', 'received_at'):
            if record.get(key) != reference.get(key):
                raise ValueError('Source receipt identity/time mismatch: ' + key)
        if record['decoded']['sha256'] != reference['decoded_sha256']:
            raise ValueError('Source receipt decoded hash mismatch')
        for key in ('wire', 'decoded'):
            blob = record[key]
            if type(blob['bytes']) != int or not 0 <= blob['bytes'] <= 67108864:
                raise ValueError('Source response exceeds byte bound')
            with gzip.GzipFile(fileobj=io.BytesIO(vault._path(blob['path']).read_bytes())) as handle:
                payload = handle.read(blob['bytes'] + 1)
            if len(payload) != blob['bytes'] or hashlib.sha256(payload).hexdigest() != blob['sha256']:
                raise ValueError('Source response byte integrity mismatch: ' + key)
        return {'status': 'verified', 'request_url': record['request_url'],
                'final_url': record['final_url'], 'received_at': record['received_at'],
                'receipt_sha256': reference['receipt_sha256'], 'decoded_sha256': reference['decoded_sha256']}

    def _new_blob(self,payload):
        digest=hashlib.sha256(payload).hexdigest();relative='payloads/'+digest+'.bin.gz';path=self._path(relative)
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(path.read_bytes())) as handle:existing=handle.read(len(payload)+1)
                valid=hashlib.sha256(existing).hexdigest()==digest
            except (OSError,EOFError,zlib.error):valid=False
            if not valid:
                # Preserve damaged bytes for diagnosis before restoring a newly received response.
                quarantine=self._path('quarantine/'+digest+'-'+uuid.uuid4().hex+'.bin.gz')
                quarantine.parent.mkdir(parents=True,exist_ok=True);os.replace(path,quarantine)
        try:
            with path.open('xb') as handle:handle.write(gzip.compress(payload,mtime=0))
        except FileExistsError:pass
        return {'path':relative,'sha256':digest,'bytes':len(payload)}

    def _journal(self,record):
        stamp=record['received_at'];name=stamp.replace(':','-')+'-'+uuid.uuid4().hex+'.json'
        relative='receipts/'+name;path=self._path(relative);path.parent.mkdir(parents=True,exist_ok=True)
        data=encoded(record)
        with path.open('xb') as handle:handle.write(data)
        event={'receipt_path':relative,'status':record['status'],'request_id':record['request_id'],
               'received_at':stamp,'request_url':record['request_url'],'receipt_sha256':hashlib.sha256(data).hexdigest()}
        self.events.append(event);return event

    def store(self,request_id,request_url,final_url,wire,decoded,*,headers,status=200,received_at=None,cacheable=True):
        received_at=received_at or datetime.now(timezone.utc).isoformat()
        record={'schema_version':1,'request_id':request_id,'request_url':request_url,'final_url':final_url,
                'received_at':received_at,'status':'http_ok' if status==200 and cacheable else 'decode_failed' if status==200 else 'http_error',
                'http_status':status,'headers':headers,'wire':self._new_blob(wire),'decoded':self._new_blob(decoded)}
        event=self._journal(record)
        if status==200 and cacheable:
            cache=self._path('cache/'+request_id+'.json');cache.parent.mkdir(parents=True,exist_ok=True)
            temporary=cache.with_name(cache.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_bytes(encoded({'receipt_path':event['receipt_path'],'receipt_sha256':event['receipt_sha256']}));os.replace(temporary,cache)
        return {**event,'transport':'network','decoded_sha256':record['decoded']['sha256']}

    def reject(self,event,reason):
        request_id=event.get('request_id');receipt=event.get('receipt_path')
        if not request_id or not receipt:return
        pointer_path=self._path('cache/'+request_id+'.json')
        try:
            pointer=json.loads(pointer_path.read_bytes())
            if pointer.get('receipt_path')==receipt:pointer_path.unlink()
        except FileNotFoundError:pass
        self.failure(request_id,event.get('request_url',''),reason,status='response_rejected_by_parser_or_contract')

    def failure(self,request_id,request_url,error,*,status='network_failed'):
        return self._journal({'schema_version':1,'request_id':request_id,'request_url':request_url,
                'received_at':datetime.now(timezone.utc).isoformat(),'status':status,'error':error})

    def cached(self,request_id,*,max_age_seconds,now=None):
        if max_age_seconds<=0:return None
        now=time.time() if now is None else now
        try:
            pointer=json.loads(self._path('cache/'+request_id+'.json').read_bytes())
            if 'receipt_sha256' not in pointer:
                self.events.append({'request_id':request_id,'status':'legacy_cache_pointer_unverified'});return None
            receipt_data=self._path(pointer['receipt_path']).read_bytes()
            if hashlib.sha256(receipt_data).hexdigest()!=pointer['receipt_sha256']:raise ValueError('Cached receipt metadata integrity mismatch')
            record=json.loads(receipt_data)
            if record['request_id']!=request_id or record['http_status']!=200 or record['status']!='http_ok':return None
            received=datetime.fromisoformat(record['received_at']).timestamp();age=now-received
            if age<0 or age>max_age_seconds:return None
            reference=record['decoded']
            if type(reference['bytes'])!=int or not 0<=reference['bytes']<=67108864:raise ValueError('Cached response exceeds size bound')
            with gzip.GzipFile(fileobj=io.BytesIO(self._path(reference['path']).read_bytes())) as handle:payload=handle.read(reference['bytes']+1)
            if len(payload)!=reference['bytes'] or hashlib.sha256(payload).hexdigest()!=reference['sha256']:
                raise ValueError('Cached response integrity mismatch')
            event={'receipt_path':pointer['receipt_path'],'status':'cache_hit','request_id':request_id,
                   'received_at':record['received_at'],'read_at':datetime.now(timezone.utc).isoformat(),
                   'request_url':record['request_url'],'transport':'cache','age_seconds':age,
                   'receipt_sha256':pointer['receipt_sha256'],
                   'decoded_sha256':reference['sha256']}
            self.events.append(event)
            return payload,record['final_url'],event
        except FileNotFoundError:return None
        except (ValueError,KeyError,TypeError,OSError,EOFError,zlib.error,json.JSONDecodeError):
            self.events.append({'request_id':request_id,'status':'cache_integrity_failed'});return None
