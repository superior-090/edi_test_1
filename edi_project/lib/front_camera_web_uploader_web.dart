import 'dart:async';
import 'dart:convert';
import 'dart:html' as html;

import 'package:web_socket_channel/web_socket_channel.dart';

html.VideoElement? _video;
html.MediaStream? _stream;
Future<html.VideoElement>? _videoFuture;

Future<Map<String, dynamic>?> uploadBrowserFrontFrame({
  required Uri uploadUri,
  required String? token,
}) async {
  final video = await _ensureVideo();
  final width = video.videoWidth > 0 ? video.videoWidth : 640;
  final height = video.videoHeight > 0 ? video.videoHeight : 480;
  final canvas = html.CanvasElement(width: width, height: height);
  canvas.context2D.drawImageScaled(video, 0, 0, width, height);

  final blob = await _canvasBlob(canvas);
  final form = html.FormData()
    ..appendBlob('file', blob, 'front-camera-browser.jpg');
  final headers = <String, String>{
    if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
  };
  final request = await html.HttpRequest.request(
    uploadUri.toString(),
    method: 'POST',
    requestHeaders: headers,
    sendData: form,
  ).timeout(const Duration(seconds: 5));
  final text = request.responseText ?? '{}';
  final decoded = jsonDecode(text);
  return decoded is Map ? Map<String, dynamic>.from(decoded) : null;
}

Future<bool> sendBrowserFrontFrameOverWebSocket(Object? channel) async {
  if (channel is! WebSocketChannel) return false;
  final dataUrl = await captureBrowserFrontFrameDataUrl();
  channel.sink.add(jsonEncode({'type': 'front_frame', 'data': dataUrl}));
  return true;
}

Future<String> captureBrowserFrontFrameDataUrl() async {
  final video = await _ensureVideo();
  final width = video.videoWidth > 0 ? video.videoWidth : 640;
  final height = video.videoHeight > 0 ? video.videoHeight : 480;
  final canvas = html.CanvasElement(width: width, height: height);
  canvas.context2D.drawImageScaled(video, 0, 0, width, height);
  return canvas.toDataUrl('image/jpeg', 0.72);
}

Future<html.VideoElement> _ensureVideo() {
  final existing = _video;
  if (existing != null && _stream != null) return Future.value(existing);
  return _videoFuture ??= _startVideo();
}

Future<html.VideoElement> _startVideo() async {
  final mediaDevices = html.window.navigator.mediaDevices;
  if (mediaDevices == null) {
    throw StateError('Browser camera API is unavailable');
  }
  final stream = await mediaDevices.getUserMedia({
    'audio': false,
    'video': {'facingMode': 'user'},
  });
  final video = html.VideoElement()
    ..autoplay = true
    ..muted = true
    ..srcObject = stream
    ..style.position = 'fixed'
    ..style.left = '-2px'
    ..style.top = '-2px'
    ..style.width = '1px'
    ..style.height = '1px'
    ..style.opacity = '0'
    ..style.pointerEvents = 'none';
  html.document.body?.children.add(video);
  await video.play();
  if (video.videoWidth == 0 || video.videoHeight == 0) {
    await video.onLoadedMetadata.first.timeout(const Duration(seconds: 3));
  }
  _stream = stream;
  _video = video;
  return video;
}

Future<html.Blob> _canvasBlob(html.CanvasElement canvas) {
  return canvas.toBlob('image/jpeg', 0.72);
}
