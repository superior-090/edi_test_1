import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'app_state.dart';
import 'video_screen.dart';

class AdminPanel extends StatefulWidget {
  const AdminPanel({super.key});

  @override
  State<AdminPanel> createState() => _AdminPanelState();
}

class _AdminPanelState extends State<AdminPanel> {
  WebSocketChannel? _channel;
  Timer? _reconnectTimer;
  Timer? _heartbeatTimer;
  bool _connected = false;
  bool _loading = true;
  String _subject = 'ALL';

  final Map<String, Map<String, dynamic>> _sessions = {};
  final List<Map<String, dynamic>> _events = [];
  Map<String, dynamic> _stats = {
    'total_active': 0,
    'total_cheating': 0,
    'total_high_risk': 0,
    'total_submitted': 0,
    'total_events': 0,
  };

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadDashboard();
      _connect();
    });
  }

  Future<void> _loadDashboard() async {
    setState(() => _loading = true);
    final api = context.read<AppState>().api;
    try {
      final sessions = await api.getSessions(subject: _subject);
      final stats = await api.getDashboardStats();
      final events = await api.getEvents();
      if (!mounted) return;
      setState(() {
        _sessions
          ..clear()
          ..addEntries(
            sessions.map((item) {
              final map = Map<String, dynamic>.from(item as Map);
              return MapEntry(map['session_id'].toString(), map);
            }),
          );
        _stats = stats;
        _events
          ..clear()
          ..addAll(
            events.map((item) => Map<String, dynamic>.from(item as Map)),
          );
      });
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Dashboard refresh failed: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _connect() {
    try {
      _channel?.sink.close();
      _channel = WebSocketChannel.connect(
        Uri.parse(context.read<AppState>().api.adminWebSocketUrl()),
      );
      setState(() => _connected = true);
      _heartbeatTimer?.cancel();
      _heartbeatTimer = Timer.periodic(const Duration(seconds: 20), (_) {
        try {
          _channel?.sink.add(jsonEncode({'type': 'ping'}));
        } catch (error, stackTrace) {
          debugPrint('Admin websocket ping failed: $error\n$stackTrace');
          _scheduleReconnect();
        }
      });
      _channel!.stream.listen(
        (data) {
          try {
            final decoded = jsonDecode(data as String) as Map<String, dynamic>;
            if (decoded['type'] == 'pong') return;
            _handleRealtime(decoded);
          } catch (error, stackTrace) {
            debugPrint('Admin realtime decode failed: $error\n$stackTrace');
          }
        },
        onError: (error, stackTrace) {
          debugPrint('Admin websocket error: $error\n$stackTrace');
          _scheduleReconnect();
        },
        onDone: _scheduleReconnect,
      );
      unawaited(_loadDashboard());
    } catch (error, stackTrace) {
      debugPrint('Admin websocket connect failed: $error\n$stackTrace');
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (!mounted) return;
    setState(() => _connected = false);
    _heartbeatTimer?.cancel();
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), _connect);
  }

  void _handleRealtime(Map<String, dynamic> data) {
    if (data['type'] == 'dashboard_snapshot' && data['sessions'] is List) {
      final sessions = (data['sessions'] as List)
          .map((item) => Map<String, dynamic>.from(item as Map))
          .where((item) => _subject == 'ALL' || item['subject'] == _subject)
          .toList();
      setState(() {
        _sessions
          ..clear()
          ..addEntries(
            sessions.map(
              (item) => MapEntry(item['session_id'].toString(), item),
            ),
          );
        _recalculateStats();
      });
      return;
    }
    final sessionId = data['session_id']?.toString();
    if (sessionId == null) return;
    final dataSubject = data['subject']?.toString();
    if (_subject != 'ALL' && dataSubject != null && dataSubject != _subject) {
      setState(() {
        _sessions.remove(sessionId);
        _recalculateStats();
      });
      return;
    }
    setState(() {
      final merged = {...?_sessions[sessionId], ...data};
      final current =
          merged['is_active'] == true || merged['approval_status'] == 'PENDING';
      if (current) {
        _sessions[sessionId] = merged;
      } else {
        _sessions.remove(sessionId);
      }
      final latest = data['latest_event'];
      if (current && latest is Map) {
        _events.insert(0, Map<String, dynamic>.from(latest));
        if (_events.length > 80) _events.removeLast();
      }
      _recalculateStats();
    });
  }

  void _recalculateStats() {
    final values = _sessions.values;
    _stats = {
      'total_active': values.where((item) => item['is_active'] == true).length,
      'total_cheating': values
          .where(
            (item) =>
                item['is_active'] == true &&
                (item['is_cheating'] == true || item['cheating'] == true),
          )
          .length,
      'total_high_risk': values
          .where(
            (item) =>
                item['risk_level'] == 'HIGH' ||
                item['risk_level'] == 'CRITICAL',
          )
          .length,
      'total_submitted': values
          .where((item) => item['is_submitted'] == true)
          .length,
      'total_events': _events.length,
    };
  }

  Future<void> _flag(String sessionId) async {
    final result = await context.read<AppState>().api.flagSession(sessionId);
    _handleRealtime({'session_id': sessionId, ...result});
  }

  Future<void> _terminate(String sessionId) async {
    final result = await context.read<AppState>().api.terminateSession(
      sessionId,
    );
    _handleRealtime({'session_id': sessionId, ...result});
  }

  Future<void> _approve(String sessionId) async {
    final result = await context.read<AppState>().api.approveRejoin(sessionId);
    _handleRealtime({'session_id': sessionId, ...result});
  }

  Future<void> _deny(String sessionId) async {
    final result = await context.read<AppState>().api.denyRejoin(sessionId);
    _handleRealtime({'session_id': sessionId, ...result});
  }

  @override
  void dispose() {
    _channel?.sink.close();
    _reconnectTimer?.cancel();
    _heartbeatTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sorted = _sessions.entries.toList()
      ..sort((a, b) {
        final scoreA = ((a.value['cheat_score'] ?? 0) as num).toDouble();
        final scoreB = ((b.value['cheat_score'] ?? 0) as num).toDouble();
        return scoreB.compareTo(scoreA);
      });

    return Scaffold(
      appBar: AppBar(
        title: const Text('Live Proctor Dashboard'),
        actions: [
          _ConnectionChip(connected: _connected),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: _loadDashboard,
          ),
          IconButton(
            tooltip: 'Logout',
            icon: const Icon(Icons.logout),
            onPressed: () async {
              await context.read<AppState>().logout();
              if (context.mounted) {
                Navigator.pushReplacementNamed(context, '/login');
              }
            },
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : LayoutBuilder(
              builder: (context, constraints) {
                final wide = constraints.maxWidth >= 1100;
                final dashboard = ListView(
                  padding: EdgeInsets.fromLTRB(18, 18, 18, wide ? 18 : 208),
                  children: [
                    _SubjectFilter(
                      selected: _subject,
                      onChanged: (value) {
                        setState(() => _subject = value);
                        _loadDashboard();
                      },
                    ),
                    const SizedBox(height: 16),
                    _StatsBar(stats: _stats),
                    const SizedBox(height: 16),
                    GridView.builder(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: sorted.length,
                      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: constraints.maxWidth > 1400
                            ? 3
                            : wide
                            ? 2
                            : 1,
                        crossAxisSpacing: 14,
                        mainAxisSpacing: 14,
                        mainAxisExtent: 520,
                      ),
                      itemBuilder: (context, index) {
                        final entry = sorted[index];
                        return _CandidateCard(
                          session: entry.value,
                          onOpen: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) => VideoScreen(sessionId: entry.key),
                            ),
                          ),
                          onFlag: () => _flag(entry.key),
                          onTerminate: () => _terminate(entry.key),
                          onApprove: () => _approve(entry.key),
                          onDeny: () => _deny(entry.key),
                        );
                      },
                    ),
                    if (sorted.isEmpty) const _EmptyDashboard(),
                  ],
                );
                return Row(
                  children: [
                    Expanded(flex: 3, child: dashboard),
                    if (wide)
                      SizedBox(width: 360, child: _EventLog(events: _events)),
                  ],
                );
              },
            ),
      bottomSheet: MediaQuery.of(context).size.width < 1100
          ? SizedBox(height: 190, child: _EventLog(events: _events))
          : null,
    );
  }
}

class _StatsBar extends StatelessWidget {
  const _StatsBar({required this.stats});

  final Map<String, dynamic> stats;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: [
        _StatTile(
          icon: Icons.people,
          label: 'Active',
          value: '${stats['total_active'] ?? 0}',
          color: Colors.cyanAccent,
        ),
        _StatTile(
          icon: Icons.warning_amber,
          label: 'Cheating',
          value: '${stats['total_cheating'] ?? 0}',
          color: Colors.redAccent,
        ),
        _StatTile(
          icon: Icons.shield,
          label: 'High risk',
          value: '${stats['total_high_risk'] ?? 0}',
          color: Colors.orangeAccent,
        ),
        _StatTile(
          icon: Icons.task_alt,
          label: 'Submitted',
          value: '${stats['total_submitted'] ?? 0}',
          color: Colors.greenAccent,
        ),
      ],
    );
  }
}

class _SubjectFilter extends StatelessWidget {
  const _SubjectFilter({required this.selected, required this.onChanged});

  final String selected;
  final ValueChanged<String> onChanged;

  static const subjects = [
    ('ALL', 'All subjects'),
    ('CS', 'Computer Science'),
    ('AI', 'AI and Ethics'),
    ('SEC', 'Digital Security'),
  ];

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SegmentedButton<String>(
        segments: [
          for (final subject in subjects)
            ButtonSegment(
              value: subject.$1,
              label: Text(subject.$2),
              icon: const Icon(Icons.menu_book),
            ),
        ],
        selected: {selected},
        onSelectionChanged: (value) => onChanged(value.first),
      ),
    );
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });

  final IconData icon;
  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 180,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF0F172A),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  color: color,
                  fontWeight: FontWeight.w900,
                ),
              ),
              Text(label, style: const TextStyle(color: Colors.white60)),
            ],
          ),
        ],
      ),
    );
  }
}

class _CandidateCard extends StatelessWidget {
  const _CandidateCard({
    required this.session,
    required this.onOpen,
    required this.onFlag,
    required this.onTerminate,
    required this.onApprove,
    required this.onDeny,
  });

  final Map<String, dynamic> session;
  final VoidCallback onOpen;
  final VoidCallback onFlag;
  final VoidCallback onTerminate;
  final VoidCallback onApprove;
  final VoidCallback onDeny;

  @override
  Widget build(BuildContext context) {
    final risk = (session['risk_level'] ?? 'LOW').toString();
    final color = risk == 'CRITICAL' || risk == 'HIGH'
        ? Colors.redAccent
        : risk == 'MEDIUM'
        ? Colors.orangeAccent
        : Colors.greenAccent;
    final score = ((session['cheat_score'] ?? 0) as num).toDouble();
    final active = session['is_active'] == true;
    final pending = session['approval_status'] == 'PENDING';

    return Card(
      child: InkWell(
        onTap: onOpen,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  CircleAvatar(
                    backgroundColor: color.withValues(alpha: 0.15),
                    child: Icon(
                      active ? Icons.person : Icons.person_off,
                      color: color,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          (session['student_name'] ?? 'Candidate').toString(),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                        Text(
                          (session['exam_title'] ?? 'Exam').toString(),
                          style: const TextStyle(color: Colors.white60),
                        ),
                        Text(
                          'Subject ${session['subject'] ?? 'GENERAL'}',
                          style: const TextStyle(
                            color: Colors.white38,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                  _RiskBadge(risk: risk, color: color),
                ],
              ),
              const SizedBox(height: 14),
              _DashboardCameraPair(
                sessionId: session['session_id']?.toString() ?? '',
              ),
              const SizedBox(height: 12),
              LinearProgressIndicator(
                value: score / 100,
                color: color,
                backgroundColor: Colors.white10,
              ),
              const SizedBox(height: 8),
              Text(
                'Cheating probability ${score.toStringAsFixed(0)}%',
                style: TextStyle(color: color, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 8),
              Text(
                (session['message'] ?? session['cheat_message'] ?? 'Clear')
                    .toString(),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Colors.white70),
              ),
              const SizedBox(height: 6),
              Text(
                'Cheat type: ${session['cheat_type']?.toString().isNotEmpty == true ? session['cheat_type'] : 'None'}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Colors.white60,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Side cam: ${session['side_camera_status'] ?? 'UNKNOWN'}',
                style: TextStyle(
                  color: session['side_camera_status'] == 'ONLINE'
                      ? Colors.greenAccent
                      : Colors.orangeAccent,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const Spacer(),
              pending
                  ? Row(
                      children: [
                        Expanded(
                          child: FilledButton.icon(
                            onPressed: onApprove,
                            icon: const Icon(Icons.check),
                            label: const Text('Allow'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: onDeny,
                            icon: const Icon(Icons.close),
                            label: const Text('Deny'),
                          ),
                        ),
                      ],
                    )
                  : Row(
                      children: [
                        _TinyMetric(
                          label: 'Warnings',
                          value: '${session['warning_count'] ?? 0}',
                        ),
                        const SizedBox(width: 10),
                        _TinyMetric(
                          label: 'Tabs',
                          value: '${session['tab_switch_count'] ?? 0}',
                        ),
                        const Spacer(),
                        IconButton(
                          tooltip: 'Open feed',
                          onPressed: onOpen,
                          icon: const Icon(Icons.videocam),
                        ),
                        IconButton(
                          tooltip: 'Flag',
                          onPressed: onFlag,
                          icon: const Icon(Icons.flag),
                        ),
                        IconButton(
                          tooltip: 'Terminate',
                          onPressed: active ? onTerminate : null,
                          icon: const Icon(Icons.stop_circle),
                        ),
                      ],
                    ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DashboardCameraPair extends StatefulWidget {
  const _DashboardCameraPair({required this.sessionId});

  final String sessionId;

  @override
  State<_DashboardCameraPair> createState() => _DashboardCameraPairState();
}

class _DashboardCameraPairState extends State<_DashboardCameraPair> {
  Timer? _timer;
  int _cacheKey = 0;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) {
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
    if (widget.sessionId.isEmpty) return const SizedBox.shrink();
    final api = context.read<AppState>().api;
    return Row(
      children: [
        Expanded(
          child: _DashboardCameraThumb(
            label: 'Front',
            url: api.getSnapshotUrl(widget.sessionId, _cacheKey),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _DashboardCameraThumb(
            label: 'Side',
            url: api.getSideSnapshotUrl(widget.sessionId, _cacheKey),
          ),
        ),
      ],
    );
  }
}

class _DashboardCameraThumb extends StatelessWidget {
  const _DashboardCameraThumb({required this.label, required this.url});

  final String label;
  final String url;

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 4 / 3,
      child: Container(
        decoration: BoxDecoration(
          color: Colors.black,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.white12),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          fit: StackFit.expand,
          children: [
            Image.network(
              url,
              fit: BoxFit.cover,
              gaplessPlayback: true,
              errorBuilder: (context, error, stackTrace) => const Center(
                child: Icon(Icons.videocam_off, color: Colors.white38),
              ),
            ),
            Positioned(
              left: 6,
              top: 6,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                decoration: BoxDecoration(
                  color: Colors.black54,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  label,
                  style: const TextStyle(
                    color: Colors.white70,
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EventLog extends StatelessWidget {
  const _EventLog({required this.events});

  final List<Map<String, dynamic>> events;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFF0B1020),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(14),
            child: Text(
              'Activity Logs',
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
            ),
          ),
          Expanded(
            child: events.isEmpty
                ? const Center(
                    child: Text(
                      'No events yet',
                      style: TextStyle(color: Colors.white38),
                    ),
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                    itemCount: events.length,
                    separatorBuilder: (context, index) =>
                        const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final event = events[index];
                      return ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          Icons.bolt,
                          color: _eventColor(event['severity']?.toString()),
                        ),
                        title: Text(
                          event['message']?.toString() ?? 'Event',
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          '${event['session_id'] ?? ''} - ${event['event_type'] ?? ''}',
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Color _eventColor(String? severity) {
    return switch (severity) {
      'CRITICAL' || 'HIGH' => Colors.redAccent,
      'MEDIUM' => Colors.orangeAccent,
      _ => Colors.cyanAccent,
    };
  }
}

class _ConnectionChip extends StatelessWidget {
  const _ConnectionChip({required this.connected});

  final bool connected;

  @override
  Widget build(BuildContext context) {
    final color = connected ? Colors.greenAccent : Colors.orangeAccent;
    return Center(
      child: Container(
        margin: const EdgeInsets.only(right: 8),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(30),
          border: Border.all(color: color.withValues(alpha: 0.35)),
        ),
        child: Text(
          connected ? 'Realtime' : 'Reconnecting',
          style: TextStyle(color: color, fontWeight: FontWeight.w800),
        ),
      ),
    );
  }
}

class _RiskBadge extends StatelessWidget {
  const _RiskBadge({required this.risk, required this.color});

  final String risk;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(30),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        risk,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _TinyMetric extends StatelessWidget {
  const _TinyMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(value, style: const TextStyle(fontWeight: FontWeight.w900)),
        Text(
          label,
          style: const TextStyle(color: Colors.white54, fontSize: 11),
        ),
      ],
    );
  }
}

class _EmptyDashboard extends StatelessWidget {
  const _EmptyDashboard();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.all(60),
      child: Center(
        child: Text(
          'Waiting for active candidate sessions...',
          style: TextStyle(color: Colors.white54),
        ),
      ),
    );
  }
}
