import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api_service.dart';
import 'app_state.dart';
import 'design_system.dart';
import 'download_helper.dart';
import 'question_image_picker.dart';

enum _TeacherTab { dashboard, subjects, exams, students, results, violations }

class TeacherDashboard extends StatefulWidget {
  const TeacherDashboard({super.key});

  @override
  State<TeacherDashboard> createState() => _TeacherDashboardState();
}

class _TeacherDashboardState extends State<TeacherDashboard> {
  _TeacherTab _tab = _TeacherTab.dashboard;
  bool _loading = true;
  bool _busy = false;
  Map<String, dynamic> _summary = {};
  List<Map<String, dynamic>> _subjects = [];
  List<Map<String, dynamic>> _exams = [];
  List<Map<String, dynamic>> _students = [];
  List<Map<String, dynamic>> _results = [];
  List<Map<String, dynamic>> _violations = [];
  final _searchController = TextEditingController();
  String _branchFilter = '';
  String _divisionFilter = '';
  int? _subjectFilter;
  int _resultSortIndex = 0;
  bool _resultAscending = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadAll());
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  ApiService get _api => context.read<AppState>().api;

  Future<void> _loadAll() async {
    setState(() => _loading = true);
    try {
      final summary = await _api.getTeacherSummary();
      final subjects = await _api.getTeacherSubjects();
      final exams = await _api.getTeacherExams();
      if (!mounted) return;
      setState(() {
        _summary = summary;
        _subjects = _maps(subjects);
        _exams = _maps(exams);
      });
      await _loadCurrentTab(showLoading: false);
    } catch (error) {
      _showError('Teacher dashboard refresh failed: $error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadCurrentTab({bool showLoading = true}) async {
    if (showLoading) setState(() => _loading = true);
    try {
      switch (_tab) {
        case _TeacherTab.dashboard:
        case _TeacherTab.subjects:
        case _TeacherTab.exams:
          final summary = await _api.getTeacherSummary();
          final subjects = await _api.getTeacherSubjects();
          final exams = await _api.getTeacherExams(subjectId: _subjectFilter);
          setState(() {
            _summary = summary;
            _subjects = _maps(subjects);
            _exams = _maps(exams);
          });
          break;
        case _TeacherTab.students:
          final students = await _api.getTeacherStudents(
            branch: _branchFilter,
            division: _divisionFilter,
            search: _searchController.text.trim(),
          );
          setState(() => _students = _maps(students));
          break;
        case _TeacherTab.results:
          final results = await _api.getTeacherResults(
            subjectId: _subjectFilter,
            branch: _branchFilter,
            division: _divisionFilter,
            search: _searchController.text.trim(),
          );
          setState(() => _results = _sortResults(_maps(results)));
          break;
        case _TeacherTab.violations:
          final violations = await _api.getTeacherViolations(
            subjectId: _subjectFilter,
            branch: _branchFilter,
            division: _divisionFilter,
            search: _searchController.text.trim(),
          );
          setState(() => _violations = _maps(violations));
          break;
      }
    } catch (error) {
      _showError('Refresh failed: $error');
    } finally {
      if (mounted && showLoading) setState(() => _loading = false);
    }
  }

  List<Map<String, dynamic>> _maps(List<dynamic> rows) {
    return rows.map((item) => Map<String, dynamic>.from(item as Map)).toList();
  }

  List<Map<String, dynamic>> _sortResults(List<Map<String, dynamic>> rows) {
    final keys = ['student_name', 'prn', 'subject', 'marks', 'percentage', 'submitted_at', 'ai_suspicion_score', 'violation_count'];
    final key = keys[_resultSortIndex.clamp(0, keys.length - 1).toInt()];
    rows.sort((a, b) {
      final left = a[key];
      final right = b[key];
      int result;
      if (left is num && right is num) {
        result = left.compareTo(right);
      } else {
        result = left.toString().compareTo(right.toString());
      }
      return _resultAscending ? result : -result;
    });
    return rows;
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _openSubjectDialog([Map<String, dynamic>? subject]) async {
    final name = TextEditingController(text: subject?['subject_name']?.toString() ?? '');
    final code = TextEditingController(text: subject?['subject_code']?.toString() ?? '');
    final branch = TextEditingController(text: subject?['branch']?.toString() ?? 'CSE');
    final semester = TextEditingController(text: subject?['semester']?.toString() ?? '1');
    final division = TextEditingController(text: subject?['division']?.toString() ?? 'A');
    final formKey = GlobalKey<FormState>();
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(subject == null ? 'Create Subject' : 'Edit Subject'),
        content: SizedBox(
          width: 520,
          child: Form(
            key: formKey,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _DialogField(controller: name, label: 'Subject name'),
                _DialogField(controller: code, label: 'Subject code'),
                Row(
                  children: [
                    Expanded(child: _DialogField(controller: branch, label: 'Branch')),
                    const SizedBox(width: 10),
                    Expanded(child: _DialogField(controller: division, label: 'Division')),
                  ],
                ),
                _DialogField(controller: semester, label: 'Semester'),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () {
              if (formKey.currentState!.validate()) Navigator.pop(context, true);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (saved != true) return;
    final payload = {
      'subject_name': name.text.trim(),
      'subject_code': code.text.trim(),
      'branch': branch.text.trim(),
      'semester': semester.text.trim(),
      'division': division.text.trim(),
    };
    try {
      if (subject == null) {
        await _api.createTeacherSubject(payload);
      } else {
        await _api.updateTeacherSubject((subject['id'] as num).toInt(), payload);
      }
      await _loadAll();
    } catch (error) {
      _showError('Subject save failed: $error');
    }
  }

  Future<void> _openExamDialog([Map<String, dynamic>? exam]) async {
    if (_subjects.isEmpty) {
      _showError('Create a subject before creating exams.');
      return;
    }
    final title = TextEditingController(text: exam?['title']?.toString() ?? '');
    final duration = TextEditingController(text: exam?['duration_minutes']?.toString() ?? '60');
    final marks = TextEditingController(text: exam?['total_marks']?.toString() ?? '100');
    final instructions = TextEditingController(text: exam?['instructions']?.toString() ?? '');
    int selectedSubject = (exam?['subject_id'] as num?)?.toInt() ?? (_subjects.first['id'] as num).toInt();
    bool published = exam?['is_published'] == true;
    final formKey = GlobalKey<FormState>();
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: Text(exam == null ? 'Create Exam' : 'Edit Exam'),
          content: SizedBox(
            width: 620,
            child: Form(
              key: formKey,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _DialogField(controller: title, label: 'Exam title'),
                    DropdownButtonFormField<int>(
                      value: selectedSubject,
                      decoration: const InputDecoration(labelText: 'Subject', prefixIcon: Icon(Icons.menu_book)),
                      items: [
                        for (final subject in _subjects)
                          DropdownMenuItem(
                            value: (subject['id'] as num).toInt(),
                            child: Text('${subject['subject_code']} - ${subject['subject_name']}'),
                          ),
                      ],
                      onChanged: (value) => setDialogState(() => selectedSubject = value ?? selectedSubject),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(child: _DialogField(controller: duration, label: 'Duration minutes', numeric: true)),
                        const SizedBox(width: 10),
                        Expanded(child: _DialogField(controller: marks, label: 'Total marks', numeric: true)),
                      ],
                    ),
                    TextFormField(
                      controller: instructions,
                      minLines: 3,
                      maxLines: 5,
                      decoration: const InputDecoration(labelText: 'Instructions', prefixIcon: Icon(Icons.notes)),
                    ),
                    SwitchListTile(
                      value: published,
                      onChanged: (value) => setDialogState(() => published = value),
                      title: const Text('Publish exam'),
                      contentPadding: EdgeInsets.zero,
                    ),
                  ],
                ),
              ),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () {
                if (formKey.currentState!.validate()) Navigator.pop(context, true);
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (saved != true) return;
    final payload = {
      'title': title.text.trim(),
      'subject_id': selectedSubject,
      'duration_minutes': int.tryParse(duration.text.trim()) ?? 60,
      'total_marks': double.tryParse(marks.text.trim()) ?? 100,
      'instructions': instructions.text.trim(),
      'is_published': published,
    };
    try {
      if (exam == null) {
        await _api.createTeacherExam(payload);
      } else {
        await _api.updateTeacherExam((exam['id'] as num).toInt(), payload);
      }
      await _loadAll();
    } catch (error) {
      _showError('Exam save failed: $error');
    }
  }

  Future<List<Map<String, dynamic>>> _loadTeacherQuestionImages(int examId) async {
    final rows = await _api.getTeacherQuestionImages(examId);
    return _maps(rows);
  }

  Future<void> _openQuestionImages(Map<String, dynamic> exam) async {
    final examId = (exam['id'] as num).toInt();
    setState(() => _busy = true);
    List<Map<String, dynamic>> images;
    try {
      images = await _loadTeacherQuestionImages(examId);
    } catch (error) {
      _showError('Question images refresh failed: $error');
      return;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    if (!mounted) return;

    await showDialog<void>(
      context: context,
      builder: (dialogContext) {
        var uploading = false;
        var deletingId = 0;

        Future<void> refresh(StateSetter setDialogState) async {
          final updated = await _loadTeacherQuestionImages(examId);
          if (dialogContext.mounted) {
            setDialogState(() => images = updated);
          }
        }

        Future<void> upload(StateSetter setDialogState) async {
          final picked = await pickQuestionImages();
          if (picked.isEmpty || !dialogContext.mounted) return;
          setDialogState(() => uploading = true);
          try {
            await _api.uploadTeacherQuestionImages(
              examId: examId,
              images: [
                for (final image in picked)
                  QuestionImageUpload(
                    bytes: image.bytes,
                    filename: image.name,
                    contentType: image.contentType,
                  ),
              ],
            );
            await refresh(setDialogState);
          } catch (error) {
            _showError('Question upload failed: $error');
          } finally {
            if (dialogContext.mounted) {
              setDialogState(() => uploading = false);
            }
          }
        }

        Future<void> deleteImage(int imageId, StateSetter setDialogState) async {
          setDialogState(() => deletingId = imageId);
          try {
            await _api.deleteTeacherQuestionImage(imageId);
            await refresh(setDialogState);
          } catch (error) {
            _showError('Question image delete failed: $error');
          } finally {
            if (dialogContext.mounted) {
              setDialogState(() => deletingId = 0);
            }
          }
        }

        return StatefulBuilder(
          builder: (context, setDialogState) => AlertDialog(
            title: Text('Questions - ${exam['title']}'),
            content: SizedBox(
              width: 760,
              height: 480,
              child: _TeacherQuestionImageGrid(
                images: images,
                deletingId: deletingId,
                onDelete: (imageId) => deleteImage(imageId, setDialogState),
              ),
            ),
            actions: [
              TextButton(
                onPressed: uploading ? null : () => Navigator.pop(context),
                child: const Text('Close'),
              ),
              FilledButton.icon(
                onPressed: uploading ? null : () => upload(setDialogState),
                icon: uploading
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.upload_file),
                label: Text(uploading ? 'Uploading' : 'Upload images'),
              ),
            ],
          ),
        );
      },
    );
    if (mounted) await _loadCurrentTab(showLoading: false);
  }

  Future<void> _export(String format) async {
    setState(() => _busy = true);
    try {
      final download = await _api.downloadTeacherResultsExport(
        format: format,
        subjectId: _subjectFilter,
        branch: _branchFilter,
        division: _divisionFilter,
        search: _searchController.text.trim(),
      );
      await downloadBytes(
        bytes: download.bytes,
        filename: download.filename,
        contentType: download.contentType,
      );
    } catch (error) {
      _showError('Export failed: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _deleteSubject(Map<String, dynamic> subject) async {
    try {
      await _api.deleteTeacherSubject((subject['id'] as num).toInt());
      await _loadAll();
    } catch (error) {
      _showError('Delete failed: $error');
    }
  }

  Future<void> _deleteExam(Map<String, dynamic> exam) async {
    try {
      await _api.deleteTeacherExam((exam['id'] as num).toInt());
      await _loadAll();
    } catch (error) {
      _showError('Delete failed: $error');
    }
  }

  void _selectTab(_TeacherTab tab) {
    setState(() => _tab = tab);
    _loadCurrentTab();
  }

  @override
  Widget build(BuildContext context) {
    final name = context.watch<AppState>().displayName;
    return Scaffold(
      appBar: AppBar(
        title: Text('Faculty Console - $name'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _busy ? null : _loadAll,
            icon: const Icon(Icons.refresh),
          ),
          IconButton(
            tooltip: 'Logout',
            onPressed: () async {
              await context.read<AppState>().logout();
              if (context.mounted) Navigator.pushReplacementNamed(context, '/login');
            },
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: AiGradientBackground(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 980;
            final content = _loading
                ? const Center(child: CircularProgressIndicator())
                : _buildContent();
            if (!wide) {
              return Column(
                children: [
                  _TopNav(selected: _tab, onSelected: _selectTab),
                  Expanded(child: content),
                ],
              );
            }
            return Row(
              children: [
                _Sidebar(selected: _tab, onSelected: _selectTab),
                Expanded(child: content),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildContent() {
    return Stack(
      children: [
        Padding(
          padding: const EdgeInsets.all(18),
          child: switch (_tab) {
            _TeacherTab.dashboard => _buildDashboard(),
            _TeacherTab.subjects => _buildSubjects(),
            _TeacherTab.exams => _buildExams(),
            _TeacherTab.students => _buildStudents(),
            _TeacherTab.results => _buildResults(),
            _TeacherTab.violations => _buildViolations(),
          },
        ),
        if (_busy)
          const Positioned.fill(
            child: ColoredBox(
              color: Color(0x66000000),
              child: Center(child: CircularProgressIndicator()),
            ),
          ),
      ],
    );
  }

  Widget _buildDashboard() {
    return ListView(
      children: [
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _StatCard(icon: Icons.menu_book, label: 'Subjects', value: '${_summary['subjects'] ?? 0}', color: Colors.cyanAccent),
            _StatCard(icon: Icons.assignment, label: 'Exams', value: '${_summary['exams'] ?? 0}', color: Colors.greenAccent),
            _StatCard(icon: Icons.publish, label: 'Published', value: '${_summary['published_exams'] ?? 0}', color: Colors.lightBlueAccent),
            _StatCard(icon: Icons.groups, label: 'Students', value: '${_summary['students'] ?? 0}', color: Colors.orangeAccent),
            _StatCard(icon: Icons.fact_check, label: 'Results', value: '${_summary['results'] ?? 0}', color: Colors.purpleAccent),
            _StatCard(icon: Icons.warning_amber, label: 'Violations', value: '${_summary['violations'] ?? 0}', color: Colors.redAccent),
          ],
        ),
        const SizedBox(height: 18),
        _SectionHeader(
          title: 'Recent Exams',
          action: FilledButton.icon(
            onPressed: () => _openExamDialog(),
            icon: const Icon(Icons.add),
            label: const Text('Create exam'),
          ),
        ),
        const SizedBox(height: 10),
        if (_exams.isEmpty)
          const _EmptyState(icon: Icons.assignment_outlined, text: 'No exams yet')
        else
          ..._exams.take(5).map(_ExamTile.new),
      ],
    );
  }

  Widget _buildSubjects() {
    return ListView(
      children: [
        _SectionHeader(
          title: 'Subjects',
          action: FilledButton.icon(
            onPressed: () => _openSubjectDialog(),
            icon: const Icon(Icons.add),
            label: const Text('Add subject'),
          ),
        ),
        const SizedBox(height: 12),
        if (_subjects.isEmpty)
          const _EmptyState(icon: Icons.menu_book_outlined, text: 'No subjects created')
        else
          _DataShell(
            child: DataTable(
              columns: const [
                DataColumn(label: Text('Code')),
                DataColumn(label: Text('Subject')),
                DataColumn(label: Text('Branch')),
                DataColumn(label: Text('Division')),
                DataColumn(label: Text('Semester')),
                DataColumn(label: Text('Actions')),
              ],
              rows: [
                for (final subject in _subjects)
                  DataRow(cells: [
                    DataCell(Text('${subject['subject_code']}')),
                    DataCell(Text('${subject['subject_name']}')),
                    DataCell(Text('${subject['branch']}')),
                    DataCell(Text('${subject['division']}')),
                    DataCell(Text('${subject['semester']}')),
                    DataCell(Row(
                      children: [
                        IconButton(tooltip: 'Edit', onPressed: () => _openSubjectDialog(subject), icon: const Icon(Icons.edit)),
                        IconButton(tooltip: 'Delete', onPressed: () => _deleteSubject(subject), icon: const Icon(Icons.delete)),
                      ],
                    )),
                  ]),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildExams() {
    return ListView(
      children: [
        _SectionHeader(
          title: 'Exams',
          action: FilledButton.icon(
            onPressed: () => _openExamDialog(),
            icon: const Icon(Icons.add),
            label: const Text('Create exam'),
          ),
        ),
        const SizedBox(height: 12),
        _SubjectFilter(
          subjects: _subjects,
          selected: _subjectFilter,
          onChanged: (value) {
            setState(() => _subjectFilter = value);
            _loadCurrentTab();
          },
        ),
        const SizedBox(height: 12),
        if (_exams.isEmpty)
          const _EmptyState(icon: Icons.assignment_outlined, text: 'No exams found')
        else
          ..._exams.map((exam) => _ExamManageTile(
                exam: exam,
                onEdit: () => _openExamDialog(exam),
                onUpload: () => _openQuestionImages(exam),
                onDelete: () => _deleteExam(exam),
                onTogglePublish: () {
                  final updated = {...exam, 'is_published': exam['is_published'] != true};
                  _api.updateTeacherExam((exam['id'] as num).toInt(), {
                    'title': updated['title'],
                    'subject_id': updated['subject_id'],
                    'duration_minutes': updated['duration_minutes'],
                    'total_marks': updated['total_marks'],
                    'instructions': updated['instructions'] ?? '',
                    'is_published': updated['is_published'],
                  }).then((_) => _loadAll()).catchError((error) => _showError('Publish failed: $error'));
                },
              )),
      ],
    );
  }

  Widget _buildStudents() {
    return ListView(
      children: [
        _SectionHeader(title: 'Students', action: IconButton(onPressed: _loadCurrentTab, icon: const Icon(Icons.refresh))),
        const SizedBox(height: 12),
        _FilterBar(
          searchController: _searchController,
          branch: _branchFilter,
          division: _divisionFilter,
          onBranchChanged: (value) => setState(() => _branchFilter = value),
          onDivisionChanged: (value) => setState(() => _divisionFilter = value),
          onApply: _loadCurrentTab,
        ),
        const SizedBox(height: 12),
        if (_students.isEmpty)
          const _EmptyState(icon: Icons.groups_outlined, text: 'No completed student profiles found')
        else
          _DataShell(
            child: DataTable(
              columns: const [
                DataColumn(label: Text('Name')),
                DataColumn(label: Text('PRN')),
                DataColumn(label: Text('Branch')),
                DataColumn(label: Text('Division')),
                DataColumn(label: Text('Semester')),
                DataColumn(label: Text('Year')),
                DataColumn(label: Text('Email')),
              ],
              rows: [
                for (final student in _students)
                  DataRow(cells: [
                    DataCell(Text('${student['full_name']}')),
                    DataCell(Text('${student['prn']}')),
                    DataCell(Text('${student['branch']}')),
                    DataCell(Text('${student['division']}')),
                    DataCell(Text('${student['semester']}')),
                    DataCell(Text('${student['year']}')),
                    DataCell(Text('${student['email']}')),
                  ]),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildResults() {
    return ListView(
      children: [
        _SectionHeader(
          title: 'Results',
          action: Wrap(
            spacing: 8,
            children: [
              OutlinedButton.icon(onPressed: () => _export('csv'), icon: const Icon(Icons.table_view), label: const Text('CSV')),
              FilledButton.icon(onPressed: () => _export('excel'), icon: const Icon(Icons.download), label: const Text('Excel')),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _FilterBar(
          searchController: _searchController,
          branch: _branchFilter,
          division: _divisionFilter,
          subjects: _subjects,
          subject: _subjectFilter,
          onSubjectChanged: (value) => setState(() => _subjectFilter = value),
          onBranchChanged: (value) => setState(() => _branchFilter = value),
          onDivisionChanged: (value) => setState(() => _divisionFilter = value),
          onApply: _loadCurrentTab,
        ),
        const SizedBox(height: 12),
        if (_results.isEmpty)
          const _EmptyState(icon: Icons.fact_check_outlined, text: 'No submitted results yet')
        else
          _DataShell(
            child: DataTable(
              sortColumnIndex: _resultSortIndex,
              sortAscending: _resultAscending,
              columns: [
                _resultColumn('Student', 0),
                _resultColumn('PRN', 1),
                _resultColumn('Subject', 2),
                _resultColumn('Marks', 3),
                _resultColumn('%', 4),
                _resultColumn('Submitted', 5),
                _resultColumn('AI score', 6),
                _resultColumn('Violations', 7),
              ],
              rows: [
                for (final result in _results)
                  DataRow(cells: [
                    DataCell(Text('${result['student_name']}')),
                    DataCell(Text('${result['prn']}')),
                    DataCell(Text('${result['subject_code']}')),
                    DataCell(Text('${result['marks']} / ${result['total_marks']}')),
                    DataCell(Text('${result['percentage']}')),
                    DataCell(Text(_shortDate(result['submitted_at']))),
                    DataCell(Text('${result['ai_suspicion_score']}')),
                    DataCell(Text('${result['violation_count']}')),
                  ]),
              ],
            ),
          ),
      ],
    );
  }

  DataColumn _resultColumn(String label, int index) {
    return DataColumn(
      label: Text(label),
      onSort: (_, ascending) {
        setState(() {
          _resultSortIndex = index;
          _resultAscending = ascending;
          _results = _sortResults([..._results]);
        });
      },
    );
  }

  Widget _buildViolations() {
    return ListView(
      children: [
        _SectionHeader(title: 'Violations', action: IconButton(onPressed: _loadCurrentTab, icon: const Icon(Icons.refresh))),
        const SizedBox(height: 12),
        _FilterBar(
          searchController: _searchController,
          branch: _branchFilter,
          division: _divisionFilter,
          subjects: _subjects,
          subject: _subjectFilter,
          onSubjectChanged: (value) => setState(() => _subjectFilter = value),
          onBranchChanged: (value) => setState(() => _branchFilter = value),
          onDivisionChanged: (value) => setState(() => _divisionFilter = value),
          onApply: _loadCurrentTab,
        ),
        const SizedBox(height: 12),
        if (_violations.isEmpty)
          const _EmptyState(icon: Icons.verified_user_outlined, text: 'No violations found')
        else
          ..._violations.map((event) => _ViolationTile(event: event)),
      ],
    );
  }

  String _shortDate(dynamic value) {
    final text = value?.toString() ?? '';
    return text.length > 16 ? text.substring(0, 16).replaceFirst('T', ' ') : text;
  }
}

class _Sidebar extends StatelessWidget {
  const _Sidebar({required this.selected, required this.onSelected});

  final _TeacherTab selected;
  final ValueChanged<_TeacherTab> onSelected;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 230,
      color: const Color(0xFF0B1020),
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          const Padding(
            padding: EdgeInsets.all(12),
            child: Text('Teacher', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
          ),
          for (final item in _navItems)
            ListTile(
              selected: item.tab == selected,
              leading: Icon(item.icon),
              title: Text(item.label),
              onTap: () => onSelected(item.tab),
            ),
        ],
      ),
    );
  }
}

class _TopNav extends StatelessWidget {
  const _TopNav({required this.selected, required this.onSelected});

  final _TeacherTab selected;
  final ValueChanged<_TeacherTab> onSelected;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 66,
      child: ListView(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        scrollDirection: Axis.horizontal,
        children: [
          for (final item in _navItems)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                selected: item.tab == selected,
                avatar: Icon(item.icon, size: 18),
                label: Text(item.label),
                onSelected: (_) => onSelected(item.tab),
              ),
            ),
        ],
      ),
    );
  }
}

class _NavItem {
  const _NavItem(this.tab, this.label, this.icon);
  final _TeacherTab tab;
  final String label;
  final IconData icon;
}

const _navItems = [
  _NavItem(_TeacherTab.dashboard, 'Dashboard', Icons.dashboard),
  _NavItem(_TeacherTab.subjects, 'Subjects', Icons.menu_book),
  _NavItem(_TeacherTab.exams, 'Exams', Icons.assignment),
  _NavItem(_TeacherTab.students, 'Students', Icons.groups),
  _NavItem(_TeacherTab.results, 'Results', Icons.fact_check),
  _NavItem(_TeacherTab.violations, 'Violations', Icons.warning_amber),
];

class _DialogField extends StatelessWidget {
  const _DialogField({required this.controller, required this.label, this.numeric = false});
  final TextEditingController controller;
  final String label;
  final bool numeric;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextFormField(
        controller: controller,
        keyboardType: numeric ? TextInputType.number : TextInputType.text,
        decoration: InputDecoration(labelText: label),
        validator: (value) => value == null || value.trim().isEmpty ? 'Required' : null,
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, required this.action});
  final String title;
  final Widget action;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(title, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900)),
        ),
        action,
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.icon, required this.label, required this.value, required this.color});
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 180,
      padding: const EdgeInsets.all(16),
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
              Text(value, style: TextStyle(color: color, fontSize: 24, fontWeight: FontWeight.w900)),
              Text(label, style: const TextStyle(color: Colors.white60)),
            ],
          ),
        ],
      ),
    );
  }
}

class _ExamTile extends StatelessWidget {
  const _ExamTile(this.exam);
  final Map<String, dynamic> exam;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: CircleAvatar(child: Text('${exam['subject_code'] ?? '-'}')),
        title: Text('${exam['title']}'),
        subtitle: Text('${exam['duration_minutes']} min - ${exam['question_count']} images'),
        trailing: _PublishBadge(published: exam['is_published'] == true),
      ),
    );
  }
}

class _ExamManageTile extends StatelessWidget {
  const _ExamManageTile({
    required this.exam,
    required this.onEdit,
    required this.onUpload,
    required this.onDelete,
    required this.onTogglePublish,
  });

  final Map<String, dynamic> exam;
  final VoidCallback onEdit;
  final VoidCallback onUpload;
  final VoidCallback onDelete;
  final VoidCallback onTogglePublish;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            CircleAvatar(child: Text('${exam['subject_code'] ?? '-'}')),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('${exam['title']}', style: const TextStyle(fontWeight: FontWeight.w900)),
                  Text('${exam['subject_name']} - ${exam['duration_minutes']} min - ${exam['question_count']} images', style: const TextStyle(color: Colors.white60)),
                ],
              ),
            ),
            _PublishBadge(published: exam['is_published'] == true),
            IconButton(tooltip: 'Manage question images', onPressed: onUpload, icon: const Icon(Icons.upload_file)),
            IconButton(tooltip: 'Edit', onPressed: onEdit, icon: const Icon(Icons.edit)),
            IconButton(tooltip: exam['is_published'] == true ? 'Unpublish' : 'Publish', onPressed: onTogglePublish, icon: const Icon(Icons.publish)),
            IconButton(tooltip: 'Delete', onPressed: onDelete, icon: const Icon(Icons.delete)),
          ],
        ),
      ),
    );
  }
}

class _TeacherQuestionImageGrid extends StatelessWidget {
  const _TeacherQuestionImageGrid({
    required this.images,
    required this.deletingId,
    required this.onDelete,
  });

  final List<Map<String, dynamic>> images;
  final int deletingId;
  final ValueChanged<int> onDelete;

  @override
  Widget build(BuildContext context) {
    if (images.isEmpty) {
      return const Center(
        child: Text(
          'No question images uploaded for this exam',
          style: TextStyle(color: Colors.white60),
        ),
      );
    }

    final api = context.read<AppState>().api;
    return GridView.builder(
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 190,
        mainAxisSpacing: 12,
        crossAxisSpacing: 12,
        childAspectRatio: 0.86,
      ),
      itemCount: images.length,
      itemBuilder: (context, index) {
        final image = images[index];
        final id = (image['id'] as num).toInt();
        final deleting = deletingId == id;
        return Container(
          decoration: BoxDecoration(
            color: const Color(0xFF0F172A),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.white12),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Image.network(
                      api.getQuestionImageUrl(id),
                      fit: BoxFit.cover,
                      errorBuilder: (context, error, stackTrace) =>
                          const ColoredBox(
                            color: Colors.black,
                            child: Icon(Icons.broken_image),
                          ),
                    ),
                    Positioned(
                      left: 6,
                      top: 6,
                      child: _QuestionImageOrderBadge(
                        label: '${image['question_number'] ?? index + 1}',
                      ),
                    ),
                    Positioned(
                      right: 4,
                      top: 4,
                      child: IconButton.filledTonal(
                        tooltip: 'Remove image',
                        onPressed: deleting ? null : () => onDelete(id),
                        icon: deleting
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.delete, size: 18),
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(8),
                child: Text(
                  image['original_filename']?.toString() ?? 'Question image',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white70, fontSize: 12),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _QuestionImageOrderBadge extends StatelessWidget {
  const _QuestionImageOrderBadge({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.black54,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label,
        style: const TextStyle(fontWeight: FontWeight.w900),
      ),
    );
  }
}

class _PublishBadge extends StatelessWidget {
  const _PublishBadge({required this.published});
  final bool published;

  @override
  Widget build(BuildContext context) {
    final color = published ? Colors.greenAccent : Colors.orangeAccent;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(published ? 'Published' : 'Draft', style: TextStyle(color: color, fontWeight: FontWeight.w800)),
    );
  }
}

class _SubjectFilter extends StatelessWidget {
  const _SubjectFilter({required this.subjects, required this.selected, required this.onChanged});
  final List<Map<String, dynamic>> subjects;
  final int? selected;
  final ValueChanged<int?> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<int?>(
      value: selected,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'Subject filter', prefixIcon: Icon(Icons.filter_list)),
      items: [
        const DropdownMenuItem<int?>(value: null, child: Text('All subjects')),
        for (final subject in subjects)
          DropdownMenuItem<int?>(
            value: (subject['id'] as num).toInt(),
            child: Text(
              '${subject['subject_code']} - ${subject['subject_name']}',
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
      onChanged: onChanged,
    );
  }
}

class _FilterBar extends StatelessWidget {
  const _FilterBar({
    required this.searchController,
    required this.branch,
    required this.division,
    required this.onBranchChanged,
    required this.onDivisionChanged,
    required this.onApply,
    this.subjects = const [],
    this.subject,
    this.onSubjectChanged,
  });

  final TextEditingController searchController;
  final String branch;
  final String division;
  final ValueChanged<String> onBranchChanged;
  final ValueChanged<String> onDivisionChanged;
  final VoidCallback onApply;
  final List<Map<String, dynamic>> subjects;
  final int? subject;
  final ValueChanged<int?>? onSubjectChanged;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        SizedBox(
          width: 240,
          child: TextField(
            controller: searchController,
            decoration: const InputDecoration(labelText: 'Search', prefixIcon: Icon(Icons.search)),
            onSubmitted: (_) => onApply(),
          ),
        ),
        SizedBox(
          width: 150,
          child: TextField(
            controller: TextEditingController(text: branch),
            decoration: const InputDecoration(labelText: 'Branch'),
            onChanged: onBranchChanged,
          ),
        ),
        SizedBox(
          width: 150,
          child: TextField(
            controller: TextEditingController(text: division),
            decoration: const InputDecoration(labelText: 'Division'),
            onChanged: onDivisionChanged,
          ),
        ),
        if (onSubjectChanged != null)
          SizedBox(
            width: 260,
            child: _SubjectFilter(subjects: subjects, selected: subject, onChanged: onSubjectChanged!),
          ),
        FilledButton.icon(onPressed: onApply, icon: const Icon(Icons.filter_alt), label: const Text('Apply')),
      ],
    );
  }
}

class _DataShell extends StatelessWidget {
  const _DataShell({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Padding(padding: const EdgeInsets.all(8), child: child),
      ),
    );
  }
}

class _ViolationTile extends StatelessWidget {
  const _ViolationTile({required this.event});
  final Map<String, dynamic> event;

  @override
  Widget build(BuildContext context) {
    final severity = event['severity']?.toString() ?? 'INFO';
    final color = severity == 'CRITICAL' || severity == 'HIGH'
        ? Colors.redAccent
        : severity == 'MEDIUM'
        ? Colors.orangeAccent
        : Colors.cyanAccent;
    return Card(
      child: ListTile(
        leading: Icon(Icons.warning_amber, color: color),
        title: Text('${event['event_type']} - ${event['student_name']}'),
        subtitle: Text('${event['message']}\n${event['exam_title']} - ${_date(event['created_at'])}'),
        isThreeLine: true,
        trailing: Text(severity, style: TextStyle(color: color, fontWeight: FontWeight.w900)),
      ),
    );
  }

  static String _date(dynamic value) {
    final text = value?.toString() ?? '';
    return text.length > 16 ? text.substring(0, 16).replaceFirst('T', ' ') : text;
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(48),
      decoration: BoxDecoration(
        color: const Color(0xFF0F172A),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        children: [
          Icon(icon, color: Colors.white38, size: 42),
          const SizedBox(height: 12),
          Text(text, style: const TextStyle(color: Colors.white60)),
        ],
      ),
    );
  }
}
