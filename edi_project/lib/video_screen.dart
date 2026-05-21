import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';

class VideoScreen extends StatefulWidget {
  const VideoScreen({super.key, required this.sessionId});

  final String sessionId;

  @override
  State<VideoScreen> createState() => _VideoScreenState();
}

class _VideoScreenState extends State<VideoScreen> {
  Map<String, dynamic>? _detail;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    try {
      final detail = await context.read<AppState>().api.getSessionDetail(
        widget.sessionId,
      );
      if (mounted) setState(() => _detail = detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = Map<String, dynamic>.from(
      (_detail?['session'] as Map?) ?? {},
    );
    final events = ((_detail?['events'] as List?) ?? [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList();

    return Scaffold(
      appBar: AppBar(
        title: Text(session['student_name']?.toString() ?? widget.sessionId),
        actions: [
          IconButton(
            tooltip: 'Refresh details',
            onPressed: _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : LayoutBuilder(
              builder: (context, constraints) {
                final wide = constraints.maxWidth >= 1000;
                final feeds = [
                  Expanded(
                    child: _FeedPane(
                      title: 'Front camera',
                      sessionId: widget.sessionId,
                      side: false,
                    ),
                  ),
                  const SizedBox(width: 12, height: 12),
                  Expanded(
                    child: _FeedPane(
                      title: 'Side camera',
                      sessionId: widget.sessionId,
                      side: true,
                    ),
                  ),
                ];
                return Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _SessionSummary(session: session),
                      const SizedBox(height: 12),
                      Expanded(
                        flex: 3,
                        child: wide
                            ? Row(children: feeds)
                            : Column(children: feeds),
                      ),
                      const SizedBox(height: 12),
                      Expanded(child: _MalpracticeLog(events: events)),
                    ],
                  ),
                );
              },
            ),
    );
  }
}

class _FeedPane extends StatelessWidget {
  const _FeedPane({
    required this.title,
    required this.sessionId,
    required this.side,
  });

  final String title;
  final String sessionId;
  final bool side;

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          ListTile(
            dense: true,
            leading: const Icon(Icons.videocam),
            title: Text(title),
          ),
          Expanded(
            child: InteractiveViewer(
              child: _SnapshotFeed(
                sessionId: sessionId,
                side: side,
                emptyText: '$title not available yet',
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SnapshotFeed extends StatefulWidget {
  const _SnapshotFeed({
    required this.sessionId,
    required this.side,
    required this.emptyText,
  });

  final String sessionId;
  final bool side;
  final String emptyText;

  @override
  State<_SnapshotFeed> createState() => _SnapshotFeedState();
}

class _SnapshotFeedState extends State<_SnapshotFeed> {
  Timer? _timer;
  int _cacheKey = 0;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 700), (_) {
      if (mounted) setState(() => _cacheKey++);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final String url;
    if (kIsWeb && widget.side) {
      url = api.getSideStreamUrl(widget.sessionId);
    } else {
      url = widget.side
          ? api.getSideSnapshotUrl(widget.sessionId, _cacheKey)
          : api.getSnapshotUrl(widget.sessionId, _cacheKey);
    }
    return Image.network(
      url,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      webHtmlElementStrategy: WebHtmlElementStrategy.prefer,
      errorBuilder: (context, error, stackTrace) => Center(
        child: Text(
          widget.emptyText,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

class _SessionSummary extends StatelessWidget {
  const _SessionSummary({required this.session});

  final Map<String, dynamic> session;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        _Pill(label: 'Exam', value: '${session['exam_title'] ?? '-'}'),
        _Pill(label: 'Subject', value: '${session['subject'] ?? '-'}'),
        _Pill(label: 'Status', value: '${session['status'] ?? '-'}'),
        _Pill(label: 'Cheat type', value: '${session['cheat_type'] ?? '-'}'),
        _Pill(label: 'Score', value: '${session['cheat_score'] ?? 0}'),
        _Pill(
          label: 'Side cam',
          value: '${session['side_camera_status'] ?? 'UNKNOWN'}',
        ),
      ],
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Chip(
      label: Text('$label: $value'),
      avatar: const Icon(Icons.info_outline, size: 16),
    );
  }
}

class _MalpracticeLog extends StatelessWidget {
  const _MalpracticeLog({required this.events});

  final List<Map<String, dynamic>> events;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: events.isEmpty
          ? const Center(child: Text('No malpractice events recorded yet'))
          : ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: events.length,
              separatorBuilder: (context, index) => const Divider(height: 1),
              itemBuilder: (context, index) {
                final event = events[index];
                return ListTile(
                  leading: const Icon(Icons.warning_amber),
                  title: Text(event['message']?.toString() ?? 'Event'),
                  subtitle: Text(
                    '${event['event_type'] ?? ''} - ${event['severity'] ?? ''}',
                  ),
                  trailing: Text('${event['score_delta'] ?? 0}'),
                );
              },
            ),
    );
  }
}
