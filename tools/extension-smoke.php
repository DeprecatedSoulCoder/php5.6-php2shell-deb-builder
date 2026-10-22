<?php
// SPDX-License-Identifier: MIT
// Each extension is checked in a fresh CLI process with its runtime dependencies.
$name=$argv[1];
function check($value, $label) {
    if (!$value) {fwrite(STDERR, "FAIL: ".$label."\n"); exit(1);}
}
$checks=array(
 'amqp'=>function(){check(class_exists('AMQPConnection'),'AMQPConnection');},
 'apcu'=>function(){check(apcu_store('php56_smoke',array('v'=>42)),'apcu_store');check(apcu_fetch('php56_smoke')===array('v'=>42),'apcu_fetch');apcu_delete('php56_smoke');},
 'gearman'=>function(){check(class_exists('GearmanClient'),'GearmanClient');},
 'geoip'=>function(){check(function_exists('geoip_database_info'),'geoip_database_info');},
 'gmagick'=>function(){$i=new Gmagick();$i->newimage(2,2,'red');check($i->getimagewidth()===2,'Gmagick image');},
 'gnupg'=>function(){check(is_object(new gnupg()),'gnupg construction');},
 'grpc'=>function(){check(class_exists('Grpc\\Channel'),'Grpc Channel');},
 'http'=>function(){check(class_exists('http\\Client'),'HTTP Client');},
 'igbinary'=>function(){check(igbinary_unserialize(igbinary_serialize(array('v'=>42)))===array('v'=>42),'igbinary round-trip');},
 'imagick'=>function(){$i=new Imagick();$i->newImage(2,2,'red');check($i->getImageWidth()===2,'Imagick image');},
 'inotify'=>function(){$r=inotify_init();check(is_resource($r),'inotify_init');fclose($r);},
 'lua'=>function(){$l=new Lua();check($l->eval('return 2+2')===4.0,'Lua evaluation');},
 'lz4'=>function(){check(lz4_uncompress(lz4_compress('php56 test'))==='php56 test','LZ4 round-trip');},
 'mailparse'=>function(){$r=mailparse_msg_create();check(is_resource($r),'mailparse_msg_create');mailparse_msg_parse($r,"Subject: test\r\n\r\nbody\r\n");check(is_array(mailparse_msg_get_part_data($r)),'mailparse parse');mailparse_msg_free($r);},
 'memcache'=>function(){$m=new Memcache();check($m->connect('127.0.0.1',11211),'Memcache connect');check($m->set('php56_smoke',array('v'=>42),0,30),'Memcache set');check($m->get('php56_smoke')===array('v'=>42),'Memcache get');$m->delete('php56_smoke');$m->close();},
 'memcached'=>function(){$m=new Memcached();$m->addServer('127.0.0.1',11211);foreach(array(Memcached::SERIALIZER_PHP,Memcached::SERIALIZER_IGBINARY,Memcached::SERIALIZER_JSON,Memcached::SERIALIZER_JSON_ARRAY,Memcached::SERIALIZER_MSGPACK) as $serializer){check($m->setOption(Memcached::OPT_SERIALIZER,$serializer),'Memcached serializer');check($m->set('php56_smoke',array('v'=>42),30),'Memcached set');$value=$m->get('php56_smoke');check($serializer===Memcached::SERIALIZER_JSON ? (is_object($value) && $value->v===42) : $value===array('v'=>42),'Memcached get');}$m->delete('php56_smoke');},
 'mongo'=>function(){check(class_exists('MongoClient'),'MongoClient');},
 'mongodb'=>function(){$b=MongoDB\BSON\fromPHP(array('v'=>42));$v=MongoDB\BSON\toPHP($b);check($v->v===42,'MongoDB BSON round-trip');},
 'msgpack'=>function(){check(msgpack_unserialize(msgpack_serialize(array('v'=>42)))===array('v'=>42),'MessagePack round-trip');},
 'mysqlnd-ms'=>function(){check(function_exists('mysqlnd_ms_get_stats'),'mysqlnd_ms_get_stats');},
 'oauth'=>function(){check(class_exists('OAuth') && oauth_urlencode('x y')==='x%20y','OAuth URL encoding');},
 'phalcon3'=>function(){check(class_exists('Phalcon\\Version'),'Phalcon Version');check(substr(Phalcon\Version::get(),0,3)==='3.4','Phalcon version');},
 'propro'=>function(){check(extension_loaded('propro'),'propro loaded');},
 'protobuf'=>function(){check(class_exists('Google\\Protobuf\\Internal\\Message'),'Protobuf Message');},
 'ps'=>function(){$r=ps_new();check(is_resource($r),'PostScript context');ps_delete($r);},
 'radius'=>function(){$r=radius_auth_open();check(is_resource($r),'RADIUS auth context');radius_close($r);},
 'raphf'=>function(){check(extension_loaded('raphf'),'raphf loaded');},
 'redis'=>function(){$r=new Redis();check($r->connect('127.0.0.1',6379,2),'Redis connect');$r->setOption(Redis::OPT_SERIALIZER,Redis::SERIALIZER_IGBINARY);check($r->set('php56_smoke',array('v'=>42),30),'Redis set');check($r->get('php56_smoke')===array('v'=>42),'Redis get');$r->del('php56_smoke');$r->close();},
 'rrd'=>function(){check(function_exists('rrd_create'),'rrd_create');},
 'smbclient'=>function(){$r=smbclient_state_new();check(is_resource($r),'SMB client context');smbclient_state_free($r);},
 'solr'=>function(){$d=new SolrDocument();$d->addField('id','php56');check($d->getFieldCount()===1,'SolrDocument');},
 'ssh2'=>function(){check(function_exists('ssh2_connect'),'ssh2_connect');},
 'stomp'=>function(){check(class_exists('Stomp'),'Stomp');},
 'uploadprogress'=>function(){check(function_exists('uploadprogress_get_info'),'uploadprogress_get_info');},
 'xcache'=>function(){check(function_exists('xcache_set'),'xcache_set');},
 'xdebug'=>function(){check(function_exists('xdebug_start_code_coverage'),'xdebug_start_code_coverage');},
 'xhprof'=>function(){xhprof_enable();strlen('test');check(is_array(xhprof_disable()),'XHProf profiling');},
 'yac'=>function(){check(class_exists('Yac'),'Yac');},
 'yaml'=>function(){check(yaml_parse(yaml_emit(array('v'=>42)))===array('v'=>42),'YAML round-trip');},
 'zmq'=>function(){$c=new ZMQContext();check(is_object($c->getSocket(ZMQ::SOCKET_PAIR)),'ZeroMQ socket context');},
 'zstd'=>function(){check(zstd_uncompress(zstd_compress('php56 test'))==='php56 test','Zstd round-trip');}
);
check(isset($checks[$name]),'known extension');
$checks[$name]();
echo "PASS ",$name,"\n";
