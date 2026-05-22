// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:typed_data';

class PickedQuestionImage {
  const PickedQuestionImage({
    required this.bytes,
    required this.name,
    required this.contentType,
  });

  final Uint8List bytes;
  final String name;
  final String contentType;
}

Future<PickedQuestionImage?> pickQuestionImage() async {
  final images = await pickQuestionImages(multiple: false);
  return images.isEmpty ? null : images.first;
}

Future<List<PickedQuestionImage>> pickQuestionImages({bool multiple = true}) async {
  final input = html.FileUploadInputElement()
    ..accept = 'image/*'
    ..multiple = multiple;
  input.click();
  await input.onChange.first;
  final files = input.files;
  if (files == null || files.isEmpty) return const [];

  final picked = <PickedQuestionImage>[];
  for (final file in files) {
    final reader = html.FileReader();
    reader.readAsArrayBuffer(file);
    await reader.onLoad.first;
    final result = reader.result;
    if (result is! ByteBuffer) continue;

    picked.add(PickedQuestionImage(
      bytes: Uint8List.view(result),
      name: file.name,
      contentType: _imageContentType(file.name, file.type),
    ));
  }
  return picked;
}

String _imageContentType(String filename, String browserType) {
  final type = browserType.trim().toLowerCase();
  if (type.startsWith('image/')) return type;

  final name = filename.toLowerCase();
  if (name.endsWith('.jpg') || name.endsWith('.jpeg')) return 'image/jpeg';
  if (name.endsWith('.png')) return 'image/png';
  if (name.endsWith('.webp')) return 'image/webp';
  if (name.endsWith('.gif')) return 'image/gif';
  if (name.endsWith('.bmp')) return 'image/bmp';
  return 'application/octet-stream';
}
