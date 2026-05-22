import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'design_system.dart';

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
          const Padding(
            padding: EdgeInsets.only(right: 8),
            child: Center(
              child: StatusBadge(label: 'Live session', color: AiColors.cyan, pulse: true),
            ),
          ),
          IconButton(
            tooltip: 'Refresh details',
            onPressed: _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: AiGradientBackground(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : LayoutBuilder(
                builder: (context, constraints) {
                  final wide = constraints.maxWidth >= 1080;
                  final feeds = wide
                      ? Row(
                          children: [
                            Expanded(child: _FeedPane(title: 'Front camera', sessionId: widget.sessionId, side: false)),
                            const SizedBox(width: 12),
                            Expanded(child: _FeedPane(title: 'Side camera', sessionId: widget.sessionId, side: true)),
                          ],
                        )
                      : Column(
                          children: [
                            SizedBox(height: 320, child: _FeedPane(title: 'Front camera', sessionId: widget.sessionId, side: false)),
                            const SizedBox(height: 12),
                            SizedBox(height: 320, child: _FeedPane(title: 'Side camera', sessionId: widget.sessionId, side: true)),
                          ],
                        );
                  return Padding(
                    padding: const EdgeInsets.all(16),
                    child: wide
                        ? Row(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Expanded(
                                flex: 3,
                                child: Column(
                                  children: [
                                    _SessionSummary(session: session),
                                    const SizedBox(height: 12),
                                    Expanded(child: feeds),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 12),
                              SizedBox(width: 360, child: _MalpracticeLog(events: events)),
                            ],
                          )
                        : ListView(
                            children: [
                              _SessionSummary(session: session),
                              const SizedBox(height: 12),
                              feeds,
                              const SizedBox(height: 12),
                              SizedBox(height: 360, child: _MalpracticeLog(events: events)),
                            ],
                          ),
                  );
                },
              ),
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
    return GlassCard(
      padding: EdgeInsets.zero,
      borderColor: (side ? AiColors.purple : AiColors.cyan).withValues(alpha: 0.25),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Icon(Icons.videocam, color: side ? AiColors.purple : AiColors.cyan),
                const SizedBox(width: 8),
                Expanded(child: Text(title, style: const TextStyle(fontWeight: FontWeight.w900))),
                StatusBadge(label: 'Streaming', color: side ? AiColors.purple : AiColors.cyan, pulse: true),
              ],
            ),
          ),
          Expanded(
            child: InteractiveViewer(
              child: _StreamFeed(
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

class _StreamFeed extends StatefulWidget {
  const _StreamFeed({
    required this.sessionId,
    required this.side,
    required this.emptyText,
  });

  final String sessionId;
  final bool side;
  final String emptyText;

  @override
  State<_StreamFeed> createState() => _StreamFeedState();
}

class _StreamFeedState extends State<_StreamFeed> {
  bool _hadFrame = false;

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final url = widget.side
        ? api.getSideStreamUrl(widget.sessionId)
        : api.getStreamUrl(widget.sessionId);
    debugPrint('Proctor feed attempted URL: $url');
    return Image.network(
      url,
      fit: BoxFit.contain,
      gaplessPlayback: true,
      cacheWidth: null,
      cacheHeight: null,
      webHtmlElementStrategy: kIsWeb
          ? WebHtmlElementStrategy.prefer
          : WebHtmlElementStrategy.never,
      frameBuilder: (context, child, frame, wasSynchronouslyLoaded) {
        if (frame != null || wasSynchronouslyLoaded) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && !_hadFrame) {
              debugPrint('Proctor feed image load success: $url');
              setState(() => _hadFrame = true);
            }
          });
        }
        return child;
      },
      loadingBuilder: (context, child, progress) {
        if (progress == null) return child;
        return Center(
          child: Text(
            _hadFrame ? 'Refreshing feed' : widget.emptyText,
            textAlign: TextAlign.center,
          ),
        );
      },
      errorBuilder: (context, error, stackTrace) => Center(
        child: Builder(
          builder: (context) {
            debugPrint('Proctor feed image load failure: $url; $error');
            return Text(
              _hadFrame ? 'Stream unavailable' : widget.emptyText,
              textAlign: TextAlign.center,
            );
          },
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
        SizedBox(
          width: 240,
          child: MetricTile(icon: Icons.assignment, label: 'Exam', value: '${session['exam_title'] ?? '-'}', color: AiColors.cyan),
        ),
        SizedBox(
          width: 170,
          child: MetricTile(icon: Icons.menu_book, label: 'Subject', value: '${session['subject'] ?? '-'}', color: AiColors.purple),
        ),
        SizedBox(
          width: 180,
          child: MetricTile(icon: Icons.radar, label: 'Status', value: '${session['status'] ?? '-'}', color: AiColors.green),
        ),
        SizedBox(
          width: 170,
          child: MetricTile(icon: Icons.warning_amber, label: 'Risk score', value: '${session['cheat_score'] ?? 0}', color: AiColors.red),
        ),
      ],
    );
  }
}

class _MalpracticeLog extends StatelessWidget {
  const _MalpracticeLog({required this.events});

  final List<Map<String, dynamic>> events;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: EdgeInsets.zero,
      borderColor: AiColors.red.withValues(alpha: 0.22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                const Icon(Icons.timeline, color: AiColors.red),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Suspicious Activity Timeline',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
                  ),
                ),
                StatusBadge(label: '${events.length}', color: events.isEmpty ? AiColors.green : AiColors.red),
              ],
            ),
          ),
          Expanded(
            child: events.isEmpty
          ? const Center(child: Text('No malpractice events recorded yet', style: TextStyle(color: Colors.white60)))
          : ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: events.length,
              separatorBuilder: (context, index) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final event = events[index];
                return Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AiColors.red.withValues(alpha: 0.08),
                    border: Border.all(color: AiColors.red.withValues(alpha: 0.24)),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.warning_amber, color: AiColors.red),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(event['message']?.toString() ?? 'Event', style: const TextStyle(fontWeight: FontWeight.w800)),
                            const SizedBox(height: 3),
                            Text('${event['event_type'] ?? ''} - ${event['severity'] ?? ''}', style: const TextStyle(color: Colors.white60)),
                          ],
                        ),
                      ),
                      Text('${event['score_delta'] ?? 0}', style: const TextStyle(color: AiColors.red, fontWeight: FontWeight.w900)),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
