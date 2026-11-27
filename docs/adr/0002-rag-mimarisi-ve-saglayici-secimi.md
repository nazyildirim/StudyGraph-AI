# ADR-0002: RAG Mimarisi ve Sağlayıcı Seçimleri (Issue #8)

- **Tarih:** 27 Kasım 2026
- **Durum:** Kabul Edildi (Uygulandı — `feature/rag-system`)
- **İlgili Görev:** Issue #8 — RAG Tabanlı Yapay Zekâ Öğrenme Asistanı

---

## 1. PDF İşleme Kütüphanesi: `pdfplumber` (MIT)
- **Bağlam:** Ders PDF'lerinden sayfa numarası, girintili C/Python kod blokları ve görsel/taranmış sayfa bilgisi çıkarılmalıdır.
- **Alternatifler:** `PyMuPDF` (AGPL-3.0 / ticari), `pypdf` (BSD-3-Clause), `pdfplumber` (MIT), `pypdfium2` (BSD/Apache).
- **Karar:** `pdfplumber` (`0.11.11`, MIT) seçildi; `PyMuPDF` eklenmedi.
- **Gerekçe:** `PyMuPDF`'in AGPL-3.0 lisansı ağ üzerinden sunulan projelerde kaynak paylaşım yükümlülüğü doğurur. `pypdf` font adı/koordinat bilgisini sınırlı verirken `pdfplumber` karakter düzeyinde `fontname`/`x0`/`top` ve `page.images` sağlayarak MIT lisansıyla kod bloğu ve taranmış sayfa tespiti sunar.
- **Avantajlar / Dezavantajlar:** İzin verici lisans ve güçlü yerleşim erişimi; `PyMuPDF`'e göre daha yavaş.
- **Gelecek Seçenekler:** Çok büyük PDF'ler için ticari lisanslı motor veya ayrı OCR servisi.

## 2. Parçalama Stratejisi: `StructureAwareChunker`
- **Bağlam:** Eski `text_splitter.py` sabit karakter kesimiyle C/Python kod bloklarını ortadan bölüyordu.
- **Alternatifler:** Sabit karakter kesimi, harici framework (LangChain splitter), özel `StructureAwareChunker`.
- **Karar:** Başlık, paragraf, cümle ve kod bloğu satır sınırlarını koruyan özel `StructureAwareChunker` + `enforce_token_limit`.
- **Gerekçe:** Ağır harici framework bağımlılığı olmadan Türkçe/İngilizce cümle ve C/Python girinti bütünlüğü korunur; tokenizer ile sessiz kırpma engellenir.
- **Avantajlar / Dezavantajlar:** Sıfır ek bağımlılık, tam test edilebilirlik; karmaşık PDF'lerde sezgisel sınırlar.
- **Gelecek Seçenekler:** AST tabanlı kod parçalayıcı.

## 3. Embedding Modeli ve Çalıştırma: `intfloat/multilingual-e5-small` + ONNX Runtime
- **Bağlam:** Türkçe, İngilizce ve C/Python terimlerinde yerel, ücretsiz, düşük bellekli embedding gereklidir.
- **Alternatifler:** `BAAI/bge-m3` (~2.2 GB, 8 GB RAM'de ağır), harici Gemini/OpenAI embedding API'leri (gizlilik/maliyet/internet riski), `sentence-transformers` + PyTorch (ağır kurulum), `multilingual-e5-small` + ONNX Runtime.
- **Karar:** Sabit revizyon (`614241f622f53c4eeff9890bdc4f31cfecc418b3`) fp32 `onnx/model.onnx` + `tokenizers` + `onnxruntime`.
- **Gerekçe:** MIT lisanslı, 384 boyutlu, M1 ARM64'te 7 ms sorgu süresi, PyTorch gerekmez, veri makineden çıkmaz.
- **Avantajlar / Dezavantajlar:** Offline çalışma ve hız; ~942 MB süreç RSS belleği ve dar yüksek kosinüs bandı (`0.71–0.92`).
- **Gelecek Seçenekler:** Nicemlenmiş (ARM64 uyumlu) veya daha yeni çok dilli ONNX modeller.

## 4. Vektör Depolama: PostgreSQL `BYTEA` + NumPy Cosine Similarity
- **Bağlam:** Embedding vektörlerinin saklanması ve ders bazlı filtrelenerek aranması gerekir.
- **Alternatifler:** `pgvector`, Chroma/Qdrant (ikinci veri deposu), FAISS, PostgreSQL `BYTEA` + NumPy.
- **Karar:** MVP'de `PostgresNumpyVectorStore`; `pgvector` kapsam dışı bırakıldı.
- **Gerekçe:** Tek veri kaynağı, sıfır ek eklenti/servis kurulumu, SQL seviyesinde `course_id` + `processed` izolasyonu ve mevcut `postgres:latest` Docker test ortamıyla tam uyum.
- **Avantajlar / Dezavantajlar:** Basitlik ve atomik silme tutarlılığı; yüz binlerce chunk'ta brute-force ölçeklenmez.
- **Gelecek Seçenekler:** `VectorStore` Protocol üzerinden `PgVectorStore` eklenmesi.

## 5. Alternatif Retrieval: Saf Python Okapi BM25
- **Bağlam:** Embedding modeli erişilemediğinde veya anahtar kelime/kod terimi aramasında bağımsız alternatif gerekir.
- **Alternatifler:** `rank-bm25` paketi, yalnızca semantik arama, saf Python `Bm25Retriever`.
- **Karar:** Sıfır bağımlılıklı saf Python `Bm25Retriever` (yalnızca açık `ModelNotFoundError` durumunda fallback).
- **Gerekçe:** Yetki/DB hatalarında veya E5 eşiği aşılamadığında fallback'i engelleyen katı güvenlik politikası üzerinde tam kontrol sağlar.
- **Avantajlar / Dezavantajlar:** Sıfır ek paket, teknik terimlerde güçlü; eşanlamlılarda semantik arama kadar güçlü değil.
- **Gelecek Seçenekler:** Kalibre edilmiş hibrit arama + reranker.

## 6. LLM Sağlayıcısı: Yerel Ollama + `qwen3:4b` (Harici API Kapsam Dışı)
- **Bağlam:** Gerçek LLM ile Türkçe/İngilizce konu anlatımı, kod örneği ve alıştırma üretilmelidir.
- **Alternatifler:** Gemini API (ücretsiz katmanda veri eğitim/insan incelemesi ve yaş/bölge şartları), OpenAI/Anthropic (ücretli), Ollama + `qwen3:4b` (Apache-2.0, `Q4_K_M`, 2.5 GB).
- **Karar:** Varsayılan yerel `OllamaLLMClient` (`127.0.0.1:11434`, `think: false`, JSON şeması); harici API kapsam dışı.
- **Gerekçe:** Öğrenci soruları ve akademisyen materyalleri makineden çıkmaz, API anahtarı/maliyet/internet riski yoktur.
- **Avantajlar / Dezavantajlar:** Tam gizlilik ve ücretsiz yerel demo; 8 GB M1'de `~3.2 GB` GPU belleği, `~3.1–3.6 GB` swap ve 4B modelde küçük dil/token sapmaları.
- **Gelecek Seçenekler:** Daha yüksek RAM'li sunucuda 7B–14B yerel model veya kurumsal gizlilik sözleşmeli API adaptörü (`LLMClient` Protocol üzerinden).

## 7. Yedek Cevap, Kaynak Doğrulama ve Yetkilendirme
- **Extractive Fallback:** LLM erişilemez veya 2 denemede geçersiz çıktı verirse `ExtractiveLLMClient` açık `[Yedek Çıkarımsal Mod]` uyarısıyla devreye girer (gerçek LLM gibi sunulmaz).
- **Citation Validation:** Sunucu üretimi `[S1]`..`[Sk]` kimlikleri `CitationValidator` ile doğrulanır; başlık/sayfa DB'den alınır. Yapısal doğruluk sağlanır; anlamsal factual entailment sınırı açıkça dokümante edilir.
- **CourseAccessPolicy:** Issue #6 `Role` ve `ResourceNotFoundError` (404) altyapısı yeniden kullanılır; yetki kontrolü dosya yükleme, embedding ve LLM çağrısından önce çalışır.

## 8. API Uyumluluğu ve Büyük Dosyaların Git Dışında Tutulması
- **Canonical + Frontend Uyumluluk Uçları:** `/api/v1` uçları REST standardını (`201` tek kayıt / `204` silme) korurken, öneksiz `/courses/...` uçları `MaterialManager.jsx` için güncel listeyi döndürür; her ikisi tek `MaterialService` kullanır.
- **`.gitignore` (`/models/`, `/uploads/`):** ~465 MB ONNX modeli ve kullanıcı yüklemeleri repoya alınmaz; model sabit revizyon ve SHA-256 ile yerel indirilir.
