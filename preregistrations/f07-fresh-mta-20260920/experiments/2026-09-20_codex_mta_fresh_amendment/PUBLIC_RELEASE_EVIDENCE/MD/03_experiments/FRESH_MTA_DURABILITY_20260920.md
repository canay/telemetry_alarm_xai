Publication view created at: 2026-09-20T17:53:29.801125+00:00

Date/time: 2026-09-20T17:42:36.270501+00:00
Tool: Codex
Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
Original private SHA256: 16d3826575eaf6be53eaf5ef714bb86ec34b9ea75994570edd17288ed36e3d62
View: administrative paths pseudonymized; original preserved.

# MTA dayanıklılık ve yerel teslim planı

Bu belge aynı bilimsel tasarımın MTA ortamına uygulanmasını kaydeder. Temel
Windows planı değiştirilmemiştir; aşağıdaki MTA-specific satırlar bu koşuyu
bağlar. Genel yayın ve MTA compute yetkisi kullanıcıda zaten kayıtlıdır;
ilk bilimsel birim yine bağımsız inceleme, final, gerçek prelaunch ve exact
public byte doğrulamasını bekler. Hazırlık süresi 12 saatlik bilimsel koşu
sayacını başlatmaz. Eski başarısız veya tamamlanmış bilimsel koşular açılmaz.

# F07 yeni doğrulama koşusu: dayanıklılık planı

Date/time: 2026-09-20T20:25:52+03:00
Tool: Codex
Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920
Status: MTA_TECHNICAL_PREPARATION_VERIFIED_INDEPENDENT_REVIEW_IN_PROGRESS

Bu belge ileriye dönük plandır; yeni bilimsel veri üretildiğini veya modellerin
eğitildiğini göstermez. Tamamlanmış discovery ve MTA engineering koşuları tekrar
çalıştırılmaz. Yeni 1000–1039 seed kümesi ancak bağımsız protokol incelemesi,
schema-v3 prelaunch doğrulaması ve exact public önkayıt yayınlama insan kapısı
kapandıktan sonra açılabilir. V2 delta incelemesinin girdileri dondurulmuştur.

atomic_unit: Bir seed için gen, feat, altı model, cross ve policy; bağımlılıklar adayın unit inventory dosyasındadır. Her tamamlanmış birim hash ile korunur.
planned_unit_count: 40 seed x 10 = 400; ardından tek deterministik aggregate. 4.920 birim çıktı yolu ve 51.840 policy sonuç satırı beklenir.
checkpoint_path_and_schema: Koşum kökünde checkpoints/<unit_id>.json; status=completed, unit_id, binding_sha256, attempt_id, completed_at, outputs yol-hash sözlüğü, exit_code, command, log_sha256 ve elapsed_seconds zorunludur.
atomic_write_strategy: JSON checkpoint ve durum kayıtları aynı klasörde benzersiz geçici dosya, flush/fsync ve os.replace ile yazılır; bayt readback yapılır. Ham çıktılar completed checkpointten önce doğrulanır. Yarım çıktılar sonraki denemeden önce attempts altında korunur.
resume_command: MTA mta_supervisor.py --output 2026-09-20_codex_mta_fresh_internal_replication_v1 --config <exact-MTA-launch-config>. Aynı runtime/source/seed ve ilk manifest deadline korunur. --recover-stale-lock yalnız kaydedilen parent/child PID-birth kimlikleri sonlandıktan sonra kullanılır. Komut final public binding sonrası somutlaştırılır.
resume_validation_rule: Kernel mutex alındıktan sonra binding, kaynaklar, bağımlılık sırası, dosya hashleri ve şemalar ölçülür. Completed birimler SKIPPED_HASH_VERIFIED kalır; değişmiş çıktı yeniden hesaplanarak üzeri örtülmez. İlk başlangıca bağlı 12 saatlik deadline korunur.
interruption_smoke_evidence: MTA_TECHNICAL_CUSTODY.json içindeki mta_lifecycle_v3_20260920_REPORT.json ve mta_guards_v3_20260920/REPORT.json; yeni MTA adapter kaynaklarında 6 lifecycle ve 5 ownership kontrolü. Genel /proc taramasının gecikmesi saklandı ve üç yeni adapter ile giderildi. Tamamlanmış bilimsel birim tekrar edilmedi.
per_unit_timeout: Bilimsel birim başına 900 saniye; sentetik fixture başına 30 saniye. Aşım RESOURCE_OR_TIMEOUT_STOP üretir, kısmi bilimsel sonuç terfi etmez.
whole_run_watchdog: İlk RUN_MANIFEST created_at + 12 saat; kesinti süresi dahildir, resume süreyi sıfırlamaz. Supervisor çocuk process ağacını izler; sahip kaybolursa worker parent watchdog ile kapanır.
eta_basis_and_margin: Tamamlanmış discovery kayıtlarında 10 seed/60 pooled model JSON için runtime_seconds toplamı 705.807057, en büyük model 35.037260 saniyedir. Ortam eşitliği kanıtlanmadığından bu yeni koşuya süre garantisi değildir; policy değerlendirme süresi ayrıca bilinmiyor. 12 saat bir kaynak tavanıdır, beklenen süre tahmini değildir. ETA ölçmek için eski deneyler tekrar çalıştırılmaz.
max_workers_and_thread_limits: Tek worker; OMP_NUM_THREADS, OPENBLAS_NUM_THREADS, MKL_NUM_THREADS, NUMEXPR_NUM_THREADS ve torch thread sayısı 1. Mevcut process tree below-normal priority ile çalışır.
disk_ram_resource_preflight: Her birim öncesi ve heartbeat sırasında en az 10 GiB boş disk ve 3 GiB kullanılabilir RAM; çocuk process ağacı RSS tavanı 4 GiB. Eski 10-seed discovery envanteri yaklaşık 0.978 GiB; dört kat ölçek yaklaşık 3.91 GiB yalnız ham büyüklük dayanağıdır, toplam paket boyutu garantisi değildir. Başlatma öncesi gerçek disk/RAM ölçülür.
progress_heartbeat_path_and_stall_threshold: heartbeats/<unit_id>_<attempt>.jsonl; yaklaşık 0.5 saniye cadence. 300 saniyeyi aşabilen her faz boyunca iç ilerleme veya dış process ağacı CPU/RSS örneklemesi görünürdür. Zaman sınırı 900 saniyedir; sessiz faz kısa faz olarak muaf tutulmaz.
heartbeat_cadence_schema_writer_and_atomicity: Supervisor timestamp, run_id, unit_id, attempt_id, pid, phase, phase_started_at, unit_elapsed_seconds, completed_atomic_units, planned_atomic_units, last_durable_checkpoint_at, process_tree_cpu_seconds, process_tree_rss_bytes ve sampled_pids yazar. Her JSONL satırından sonra flush/fsync; çökmede eksik son satır completed checkpoint değildir.
heartbeat_advancement_smoke_evidence: Hash doğrulanmış mta_lifecycle_v3_20260920_REPORT.json: heartbeat_reports_cpu_advancement_inside_unit. Actual MTA worker içerisinde artan CPU ve checkpoint ilerlemesi sentetik fixture ile gözlendi.
opaque_phase_supervisor_sampling_rule: MTA mta_owned_worker.py PID ve bütün recursive descendant ağacı izlenir. mta_process_tree.py tüm /proc/PID/task/TID/children listelerini birleştirir; ppid ve process creation time ile sınırlar. Supervisor ve worker bootstrap aynı helperı yükler.
raw_output_contract: Adayın exact unit inventory dosyası; NPZ finite-array ve model episode mass boyutları, JSON seed/model/episode-count, policy seed başına 1.296 satır, SHA-256 ve checkpoint dependency doğrulaması.
aggregate_script_and_inputs: seed_level_reducer.py; yalnız 40 seedin hash doğrulanmış policy/seedN/results.json kayıtları. Eksik/duplicate/bozuk hücre reddedilir. aggregate.json ve ayrı aggregate checkpoint üretilir; dört ana contrast ve zorunlu altı-model duyarlılığı saklanır.
plot_script_and_inputs: Bu prospective koşuda figür üretimi yoktur. Sonuçlar doğrulanmadan manuscript figürü oluşturulmaz; sonraki görsel işi ayrı kaynak/çıktı hashleri ve görsel QA gerektirir.
decision_artifact_path_and_criterion_schema: aggregate.json; C1>0, C2<0, C3>0, C4<0 yönleri ve dört Bonferroni %98.75 iki taraflı güven aralığının sıfırı beklenen yönde dışlaması birlikte değerlendirilir. Birincil karar başarısızlığını exploratory sonuç yükseltemez.
decision_discriminator_statistics_persisted: Her seedin contrastları, n=40, mean, sample SD ddof=1, df=39, CI uçları ve yön kararı; primary beş model ve zorunlu altı-model sensitivity ayrı. İkincil %95 aralıklar descriptive/unadjusted etiketlidir; SESOI/önem veya equivalence hükmü yoktur.
notification_lifecycle: Bu aktif Codex görevinde başlangıç, anlamlı checkpoint, hata ve terminal sonuç Türkçe bildirilir; yeni periyodik otomasyon yoktur. Orchestrator kendi izinli inceleme terminal bildirimini yönetir.
terminal_status_paths: Koşum kökünde terminal_status.json ve RUN_MANIFEST.json. provenance_v3_20260920/REPORT.json gerçek merkez manifest okuyucusuyla run_id/environment/code digest uyumunu ve resume öncesi güncel running durumunu doğruladı. Bu sentetik kanıt bilimsel terminal kaydı değildir.
predecessor_terminal_status_poll_rule: Bir önceki bilimsel koşuyu bekleyen paralel üretim başlatılmaz. Model incelemesinin gerçek terminal sonucu okunur; başarısızlıkta otomatik bilimsel çalıştırma yapılmaz. İleride bir predecessor beklenirse merkez wait_for_predecessor.py durum dosyasını izler; yalnız süreç PID'i veya bekleme damgası yeterli değildir.
container_image_layer_budget: compressed 0 GiB; uncompressed 0 GiB. Container kullanılmaz. MTA mevcut <experiment-home>/experiments/f08-c1r-20260826/venv ortamı; exact MTA_RUNTIME.json Python/paket/BLAS/thread kaydı bağlanır. Yeni venv veya merkez altyapısı kurulmaz.
phased_engine_schedule_rule: phased tek-worker bağımlılık sırası; boş disk 10 GiB altındaysa dur. Container pull/run/remove uygulanamaz; otomatik dosya silme ile kaynak açılmaz.
recovery_merge_equivalence_gate: input_byte_identity, image_identity=no_container, analyzer_version=exact source snapshot hash ve complete_cell_count=400/51.840 birlikte doğrulanmadan recovered sonuçlar birleştirilmez. Farklı runtime veya kaynak hashli iki koşu birleştirilmez.
opaque_runtime_bound_admission: mode=heartbeat; threshold_seconds=300; evidence=MTA_TECHNICAL_CUSTODY.json ile hashli mta_lifecycle_v3_20260920_REPORT.json; overrun=heartbeat_or_fail_closed
code_snapshot_path_and_sha256: Koşum İÇİNDE code_snapshot/ altında 17 değiştirilmemiş kaynak ve 3 MTA runtime adapter kopyası, toplam20 exact SHA-256 kaydı. Durable manifest kopyadan önce yazılır; verify_snapshot her birim ve resume öncesinde kontrol eder. Gerçek scientific snapshot henüz üretilmedi.
local_delivery_and_verification_rule: MTA remote run kökü exact launch confige bağlanır. İlk terminalde bütün dosyaların relative path, byte size ve SHA-256 envanteri MTAda üretilir. Arşiv üye kümesi ve arşiv SHA kaydedilir; local transfer öncesi remote digest alınır, transfer sonrası digest ve tüm açılan üyelerin hash/size/seti karşılaştırılır. Path traversal/symlink/duplicate archive member reddedilir. 400 checkpoint/4920 unit artifact/aggregate tamlığı merkezden doğrulanır. Sonuçlar yalnız tam custody sonrası analiz edilir. Syncthing yoktur; SSH/scp taşıması kullanılır.
partial_result_promotion_policy: prohibited
