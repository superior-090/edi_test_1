import 'package:flutter/foundation.dart';

class ApiConfig {
  static const _configuredApiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );
  static const _configuredApiUrl = String.fromEnvironment(
    'API_URL',
    defaultValue: '',
  );
  static const _defaultBaseUrl = String.fromEnvironment(
    'DEFAULT_API_BASE_URL',
    defaultValue: '',
  );

  static final String baseUrl = _normalizeBaseUrl(
    _configuredApiBaseUrl.isNotEmpty
        ? _configuredApiBaseUrl
        : (_configuredApiUrl.isNotEmpty ? _configuredApiUrl : _fallbackBaseUrl),
  );

  static void logSelectedBackend() {
    debugPrint('ProctorAI backend URL: $baseUrl');
    debugPrint('ProctorAI websocket URL: $webSocketBaseUrl');
  }

  static String get webSocketBaseUrl {
    final base = Uri.parse(baseUrl);
    return base
        .replace(scheme: base.scheme == 'https' ? 'wss' : 'ws')
        .toString();
  }

  static String webSocketUrl(String path, {String? token}) {
    final base = Uri.parse(webSocketBaseUrl);
    return base
        .replace(
          path: '${base.path}${path.startsWith('/') ? path : '/$path'}',
          queryParameters: {
            if (token != null && token.isNotEmpty) 'token': token,
          },
        )
        .toString();
  }

  static String _normalizeBaseUrl(String value) {
    return value.trim().replaceFirst(RegExp(r'/$'), '');
  }

  static String get _fallbackBaseUrl {
    if (_defaultBaseUrl.isNotEmpty) return _defaultBaseUrl;
    final host = Uri.base.host.toLowerCase();
    final localWeb =
        kDebugMode ||
        host == 'localhost' ||
        host == '127.0.0.1' ||
        host.startsWith('192.168.') ||
        host.startsWith('10.') ||
        RegExp(r'^172\.(1[6-9]|2\d|3[0-1])\.').hasMatch(host);
    return localWeb ? 'http://127.0.0.1:8000' : 'https://edi-3792.onrender.com';
  }
}
