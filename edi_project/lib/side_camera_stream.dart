import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

enum SideCameraStreamType { mjpeg, rtspUnsupported, invalid }

class SideCameraStreamInfo {
  const SideCameraStreamInfo({required this.url, required this.type});

  final String url;
  final SideCameraStreamType type;
}

SideCameraStreamInfo resolveSideCameraStream(String rawValue) {
  final value = rawValue.trim();
  if (value.isEmpty) {
    return const SideCameraStreamInfo(
      url: '',
      type: SideCameraStreamType.invalid,
    );
  }

  final lower = value.toLowerCase();
  if (lower.startsWith('rtsp://')) {
    return SideCameraStreamInfo(
      url: value,
      type: SideCameraStreamType.rtspUnsupported,
    );
  }

  if (lower.startsWith('http://') || lower.startsWith('https://')) {
    final uri = Uri.tryParse(value);
    if (uri == null) {
      return const SideCameraStreamInfo(
        url: '',
        type: SideCameraStreamType.invalid,
      );
    }
    final path = uri.path.replaceAll(RegExp(r'/+$'), '');
    if (path.isEmpty) {
      final streamUri = uri.replace(path: '/video');
      return SideCameraStreamInfo(
        url: streamUri.toString(),
        type: SideCameraStreamType.mjpeg,
      );
    }
    return SideCameraStreamInfo(url: value, type: SideCameraStreamType.mjpeg);
  }

  if (lower.contains('/video')) {
    return SideCameraStreamInfo(
      url: 'http://$value',
      type: SideCameraStreamType.mjpeg,
    );
  }

  final host = value.replaceAll(RegExp(r'/+$'), '');
  final url = host.contains(':')
      ? 'http://$host/video'
      : 'http://$host:8080/video';
  return SideCameraStreamInfo(url: url, type: SideCameraStreamType.mjpeg);
}

class SideCameraStreamView extends StatefulWidget {
  const SideCameraStreamView({
    super.key,
    required this.streamUrl,
    this.fit = BoxFit.cover,
    this.timeout = const Duration(seconds: 8),
    this.onConnected,
    this.onFailure,
  });

  final String streamUrl;
  final BoxFit fit;
  final Duration timeout;
  final ValueChanged<String>? onConnected;
  final ValueChanged<String>? onFailure;

  @override
  State<SideCameraStreamView> createState() => _SideCameraStreamViewState();
}

class _SideCameraStreamViewState extends State<SideCameraStreamView> {
  Timer? _timeoutTimer;
  bool _connected = false;
  bool _failed = false;
  String _message = 'Connecting to side camera...';

  @override
  void initState() {
    super.initState();
    _startAttempt();
  }

  @override
  void didUpdateWidget(covariant SideCameraStreamView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.streamUrl != widget.streamUrl) {
      _startAttempt();
    }
  }

  @override
  void dispose() {
    _timeoutTimer?.cancel();
    super.dispose();
  }

  void _startAttempt() {
    _timeoutTimer?.cancel();
    _connected = false;
    _failed = false;
    _message = 'Connecting to side camera...';
    final info = resolveSideCameraStream(widget.streamUrl);
    debugPrint(
      'Side camera attempted URL: ${info.url.isEmpty ? widget.streamUrl : info.url}',
    );

    if (info.type == SideCameraStreamType.rtspUnsupported) {
      _fail('RTSP is unsupported on Flutter Web');
      return;
    }
    if (info.type == SideCameraStreamType.invalid) {
      _fail('No side camera URL provided');
      return;
    }

    _timeoutTimer = Timer(widget.timeout, () {
      if (!_connected && mounted) {
        _fail('Timeout after ${widget.timeout.inSeconds}s');
      }
    });
    if (mounted) setState(() {});
  }

  void _connect() {
    if (!mounted) return;
    if (_connected) return;
    _timeoutTimer?.cancel();
    _connected = true;
    _failed = false;
    _message = 'Connected';
    final url = resolveSideCameraStream(widget.streamUrl).url;
    debugPrint('Side camera image load success: $url');
    widget.onConnected?.call(url);
    setState(() {});
  }

  void _fail(String reason) {
    if (!mounted) return;
    _timeoutTimer?.cancel();
    _connected = false;
    _failed = true;
    _message = 'Stream unavailable';
    final url = resolveSideCameraStream(widget.streamUrl).url;
    debugPrint('Side camera image load failure: $url; $reason');
    debugPrint('Side camera timeout reason: $reason');
    widget.onFailure?.call(reason);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final info = resolveSideCameraStream(widget.streamUrl);
    if (info.type == SideCameraStreamType.rtspUnsupported) {
      return const _SideCameraStatusBox(
        text:
            'RTSP streams are not supported in Flutter Web. Use an HTTP MJPEG URL such as http://PHONE_IP:8080/video.',
        loading: false,
      );
    }
    if (info.type == SideCameraStreamType.invalid) {
      return const _SideCameraStatusBox(
        text: 'Stream unavailable',
        loading: false,
      );
    }

    return Stack(
      fit: StackFit.expand,
      children: [
        Image.network(
          info.url,
          gaplessPlayback: true,
          fit: widget.fit,
          cacheWidth: null,
          cacheHeight: null,
          webHtmlElementStrategy: kIsWeb
              ? WebHtmlElementStrategy.prefer
              : WebHtmlElementStrategy.never,
          frameBuilder: (context, child, frame, wasSynchronouslyLoaded) {
            if (frame != null || wasSynchronouslyLoaded) {
              WidgetsBinding.instance.addPostFrameCallback((_) => _connect());
            }
            return child;
          },
          loadingBuilder: (context, child, loadingProgress) {
            if (loadingProgress == null) {
              WidgetsBinding.instance.addPostFrameCallback((_) => _connect());
              return child;
            }
            return child;
          },
          errorBuilder: (context, error, stackTrace) {
            WidgetsBinding.instance.addPostFrameCallback(
              (_) => _fail(error.toString()),
            );
            return const _SideCameraStatusBox(
              text: 'Stream unavailable',
              loading: false,
            );
          },
        ),
        if (!_connected || _failed)
          _SideCameraStatusBox(text: _message, loading: !_failed),
        if (_connected)
          const Positioned(
            left: 10,
            top: 10,
            child: _ConnectedPill(),
          ),
      ],
    );
  }
}

class _SideCameraStatusBox extends StatelessWidget {
  const _SideCameraStatusBox({required this.text, required this.loading});

  final String text;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.black,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (loading) ...[
                const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(height: 12),
              ],
              Text(
                text,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white70),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ConnectedPill extends StatelessWidget {
  const _ConnectedPill();

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.62),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.greenAccent.withValues(alpha: 0.65)),
      ),
      child: const Padding(
        padding: EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        child: Text(
          'Connected',
          style: TextStyle(
            color: Colors.greenAccent,
            fontSize: 12,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
    );
  }
}
