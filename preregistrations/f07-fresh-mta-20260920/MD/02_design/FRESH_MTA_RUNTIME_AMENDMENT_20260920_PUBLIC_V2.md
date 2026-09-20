# MTA çalışma ortamı değişikliği — yeni seed başlamadan önce

Date/time: 2026-09-20T17:11:48.172093+00:00
Tool: Codex
Model: gpt-6-astra / xhigh
Operation ID: `f07-mta-fresh-to-round-f-20260920`

Bu prospective değişiklik yalnız çalışma ortamını ve süreç gözetimini değiştirir.
Kullanıcı MTA önceliğini ve gerekirse yerel fallback'i açıkça seçmiştir. İlk
Windows sözleşmesi ve yayımlanmış paketi değişmez; orada bilimsel koşu başlamamıştır.
Aşağıdaki bilimsel tasarım aynı 40 seed, modeller, 400 birim, eşikler, kontrastlar,
çıkarım ailesi, kaynak tavanları ve eski başarısız girişim açıklamalarını korur.

Yeni birincil çalışma ortamı MTA Linux/Python 3.12.3 ve MTA_RUNTIME.json içindeki
exact paket/BLAS/thread sürümleridir. Özellikle scikit-learn 1.7.2, CPU Torch
2.11.0+cpu kullanılır; Windows sürümleriyle sayısal eşdeğerlik ileri sürülmez.
Kaynak 17 bilimsel/uygulama dosyası değişmez; üç yeni MTA adapter'ı hashlenir.
GPU donanımı olsa da sabit algoritmalar CPU ve tek sayısal thread ile çalışır.

MTA experiment-only düğümdür: merkez kodu kurulmaz. Yazar makinesindeki gerçek
schema-v3 prelaunch çıktısı hashli bir makbuzla bağlanır; aday, bağımsız inceleme,
karar, final, yayın ve ölçülen MTA ortamı gerçek başlatıcı tarafından denetlenir.
Yayın yetkisi kullanıcının GitHub paketi yayımlama ve MTA'da çalıştırma talimatıdır.
İnceleme ve final sonrası mevcut yetki exact pakete bağlanır; yeni kullanıcı
yanıtı varmış gibi kaydedilmez. Yayımlanmış byte doğrulaması koşudan önce gelir.

Sentetik test, CPU işi çalışırken genel /proc taramasının watchdog çıkışını
geciktirdiğini gösterdi. mta_process_tree.py yalnız sahip olunan PID'nin bütün
thread children listelerini dolaşır; PID/birth/ppid kontrolü yapar. Aynı helper
supervisor ve ayrı worker bootstrap'ında kurulur. Parent kaybı, output-yok/exit74,
tek sahiplik, checkpoint ve resume kontrolleri yeni MTA kaynaklarıyla geçmiştir.
Bu testler bilimsel generator/model/endpoint çalıştırması değildir.

Run ID: `2026-09-20_codex_mta_fresh_internal_replication_v1`.
MTA kökü: `<experiment-home>/experiments/SCI-f07-telemetry_alarm_xai/2026-09-20/package/`.
12 saatlik sayaç ilk gerçek RUN_MANIFEST ile başlar; teknik hazırlık bu süreye
dahil değildir. Kesinti ve resume bu sayacı sıfırlamaz. Tamamlanmış birimler
yeniden hesaplanmaz. Başka ortama fallback otomatik byte eşdeğerliği varsaymaz;
kısmi sonuçlar korunur ve yeni ortam için prospective binding gerekir.

## Değişmeyen bilimsel tasarım

Aşağıdaki tarihli temel metnin bilimsel şartları korunur; onun Windows runtime,
başlatma/yayın durumu ve merkez dependency tanımları yukarıdaki MTA değişikliğiyle
yer değiştirir. Tail dönüşümündeki ECDF tanımı, kodun mevcut query kümesinde aynı
nominal bin içi azalan average-rank/(bin-size+1) düzeltmesini de içerir; yeni
bir dönüşüm uygulanmaz. Episode peak ve flagged-window kümeleri ayrı işlenir.

# Yeni-seed içsel replikasyon — incelenecek uygulama sözleşmesi

Date/time: 2026-09-20 01:56 +03:00  
Tool: Codex  
Model, if known: gpt-6-astra / xhigh  
Operation ID: `f07-auto-preflight-20260919`

Change ID: `MCC-F07-FRESH-MATCHED-VALIDATION-20260904`.
Status: `CANDIDATE_PENDING_FINAL_INDEPENDENT_REVIEW`.
Bu aday bilimsel çalıştırma veya dış yayın izni değildir. Bağımsız son
inceleme, karar, schema-v3 ön kontrolü ve bu pakete özgü public önkayıt
yayın onayı kapanmadan yeni veri üretilmez veya model eğitilmez.

## Soru, kanıt ve tekrar etmeme sınırı

Soru, aynı tespit edilmiş alarm kuyruğu, skor ve kanal kritiklik vektörü
altında kullanılan kanal kanıtının hedefe bağlı referans-olay kapsamını
değiştirip değiştirmediğidir. Açıklama tabanlı ve yalın nominal sapma
kanıtları eşit bilgi sınırında karşılaştırılır. İnsan performansı, fiziksel
görev kaybının azalması veya yeni detector katkısı sınanmaz.

Hipotez yönleri eski discovery sonuçları görüldükten sonra belirlenmiştir.
Yeni test aynı generator ailesinin yeni seed'leridir; gerçek veri dış
geçerliği veya teori düzeyinde bağımsızlık kanıtı olarak sunulmaz. Yakın
literatür ve yanlışlanabilir farkın kaydı
`MD/01_literature/LITERATURE_POSITIONING_SYNTHESIS_20260904.md` içindedir.
ESA-ADB dış kolu ayrı protokol ve veri/sızıntı denetimi gerektirir; bu
sözleşme o kolu başlatmaz ve onun yerine geçmez.

Tamamlanmış discovery deneyleri, MTA engineering smoke ve eski başarısız
V4/V5 koşuları tekrarlanmaz. Mevcut çıktılar yalnız hashli teknik karşılaştırma
girdisidir. Eski confirmation seed 10–29 ve 300–319 endpointleri kapalıdır.
Yeni test seed 1000–1039'dur; bu belge yazılırken bunlara erişilmemiştir.
V4 (10–29) girişiminin terminal kaydı NOT_CONFIRMED_PROPERTY_GATE'dir.
V5 (300–319) girişimi aynı terminal etiketini taşır; kayıtlı değerlendirmesi
INCONCLUSIVE_GATE_DEFECT'tir. Her iki girişimde endpoint analizi başlamamıştır.
Aday JSON, bu iki girişimin mevcut plan/kod kimliklerini ve metadata kaynaklarını
taşır; geçmişte kaydedilmemiş protocol veya snapshot hash'leri unknown kalır.

## Örnekleme, modeller ve veri sınırı

40 bağımsız generator seed'i; her seed'de yedi ayrı 130-orbit trajectory ve
ortak toplam 252 referans olay. Her trajectory ayrı segmentlenir, sonra alarm
episode kayıtları aynı seed içinde havuzlanır. Bütçe havuzlanmış kuyruğa
uygulanır; trajectory başına ayrı bütçe bu estimand değildir. Ham pencere
skorları AUROC/AP için concatenate edilir; bu, trajectory sınırları üzerinden
episode segmentlendiği anlamına gelmez.

Modeller lr, dtree, iforest, hgb, pca, ae'dir. Ana özet lr/iforest/hgb/pca/ae
üzerinde eşit ağırlıklıdır. Dtree'nin sabit dışlama gerekçesi 26 Ağustos
V1.1 protokolündeki discovery score tie-pair mass >0.50 bulgusudur
(`MD/02_design/confirmatory_heterogeneity_protocol_v1_1.md:26–30,53–55` ve
`github-telemetry_alarm_xai/PROTOCOL_V1_1.md:115–117`). Yeni seed sonuçlarına
göre model elenmez. Dtree dahil altı-model duyarlılığı ve altı tek-model
çıktısının tümü zorunludur; ana aileyi kurtarmak için kullanılmaz.

Değişmez V5 producer'ın eğitim/validation/test ve RNG düzeni korunur.
Nominal eğitim istatistikleri yalnız training'den; eşik nominal validation'dan;
denetimli modellerin tanımlı labeled-development girdisi testten ayrıdır.
Yedi test replicate'i için fit aynı RNG ile yeniden hesaplanır; aynı model
nesnesinin bir defa eğitilip reuse edildiği iddia edilmez. Bütün mean_val
vektörleri dtype ve eleman düzeyinde eşit olmalıdır. Bu kontrol fitted
parametrelerin bit eşitliği sertifikası değildir.

Policy girdisi yalnız episode_uid, finite nonnegative tail-surprisal skor
ve native/occlusion/raw_nominal_deviation/feature_nominal_deviation kanal
mass'lerini taşır. Event IDs, impact, fault type ve Xte_nominal policy
dosyasına giremez. Evaluation anahtarı ayrı JSON'dadır; model içindeki UID
kümeleriyle birleştirilir ve policy dosyasının içerik hash'ine bağlanır.
Priority alt sürecinin uygulaması yalnız bu policy dosyasını okur. Bu sınır
bir bilgi-akışı/API sınırıdır; işletim sistemi düzeyinde bir güvenlik sandbox'ı
olduğu ileri sürülmez. Hashli kaynak incelemesi bu ayrımı denetler.

## Öncelik ve utility aritmetiği

Altı policy: score_only, native, occlusion, raw_nominal_deviation,
feature_nominal_deviation, permuted_occlusion. Profil kümesi uniform ve
lambda=0,0.1,...,1 için platform→payload doğrusal karışımıdır. Platform
vektörü [4,2,2,4,4,2,1,4,2,4,4,4], payload [2,4,1,2,2,1,4,2,1,1,1,1].

Öncelik score+1e-12 ile başlar; nonuniform profil için bu değer normalize
kanal mass'inin c ile iç çarpımının mean(c)'ye oranıyla çarpılır. Uniform
profilde doğrudan aynı skor kopyalanır; aritmetik özdeşlik kontrolüdür.
Tail-surprisal finite nominal-validation ECDF dönüşümüdür; monotonluk tek
başına kritiklikle çarpılmış sıralamayı dönüşümden bağımsız yapmaz. Sonuç
bu skorlama tanımına koşulludur; raw/z-score dönüşümlerine genellenmez.

Raw baseline training ortalama/standart sapmasına göre abs sapmanın
20-sample pencerede kanal ortalamasını; feature baseline standardize 48
özelliğin dört blokta kanal başına mutlak toplamını kullanır. Kanal
normalizasyonu, sıfır toplamda uniform mass ve episode içi tail ağırlıkları
donmuş kodla aynıdır. Sonuç görülerek epsilon veya işlem sırası değiştirilmez.

Permuted_occlusion seed başına tek kanal permütasyonu kullanır:
SeedSequence[20260904,seed,431]. Bu bir null dağılımı değildir; betimsel
kontroldür. Native ve feature baseline da birincil dört kontrastın dışında
kalsa bile tüm sonuçları raporlanır.

Üç hedef birlikte üretilir: event impact_by_channel ile c iç çarpımı
`original_impact`; her olayın kanal impact'ini toplamına bölüp c ile iç
çarpım `channel_criticality_only`; her olaya 1 veren `equal_event`.
Policy ve utility aynı c'yi kullanır; bu simetri açıklanır ve fiziksel zarar
etiketi veya açıklamaya özgü üstünlük kanıtı gibi yorumlanmaz.

## Matching, bütçe ve sınırlar

Kapsam maksimum ağırlıklı bire bir alarm–referans olay matching'idir. Her
incelenen alarm en çok bir olay kredisi alır, her olay en çok bir defa
kazanılır. Bu ölçüt seçimi insan operatörün tek kök neden çözebildiğine
ilişkin kanıt değildir. Union coverage farklı bir estimand'dır.

Pozitif referans evreni ve n>=3 için legacy eğri aynen korunur: f=0.05,
0.1,0.2,0.4 için k=min(n,max(1,floor(f*n))), x=k/n; aynı x bir defa
tutulur, son değer x=0.4'e taşınır. (0,0) dahil x<=0.4 noktalarında
trapezoid integrali 0.4'e bölünür. Bu legacy uyum uzantısıdır; her n için
tek bir evrensel floor-bütçe kuralı gibi sunulmaz. Pozitif evrende n=0,1,2
için endpoint 0 ve VALID_ZERO_REVIEW_CAPACITY; referans olay yoksa None ve
NO_REFERENCE_EVENTS. 252 olaylı tasarımda son durum teknik veri hatasıdır.
Geçerli küçük/boş alarm kuyruğu seed veya model dışlama gerekçesi değildir.

Öncelikler float64; exact float eşitliği tie'dır, posthoc yuvarlama yapılmaz.
Tie yoksa stable argsort; varsa 100 ortak rastgele tie sıralaması kullanılır.
Tie seed = 20260826+100000*seed+1000*model_index+sid; model_index yukarıdaki
altı-model sırasıdır. sid uniform 0, platform 1, payload 2, iç lambda_i için
100+i'dir. Policy/utility adı tie seed'e girmez. Aynı kuyrukta karşılaştırılan
kollar ortak rastgele sayıları kullanır.

Ana sayısal ortam exact runtime JSON ile kilitlenir: Python/paket sürümleri,
işletim sistemi/mimari, BLAS/OpenMP havuzları ve thread sınırları. Eski
Windows/MTA 62/61 exact-tie farkı korunur. Bu aday tek pinli ortamda çıkarım
yapar; tam model→policy platform eşdeğerliği sertifikası vermez. Başka
platformda yalnız donmuş priority'leri değerlendirmek ayrı kapsamdır.

## Çıkarım ve tüm sonuçları raporlama

Inferans birimi seed'dir; 51.840 policy hücresi veya 280 trajectory n olarak
kullanılmaz. C1 kanal-kritiklik raw−score; C2 equal-event raw−score; C3
kanal-kritiklik raw−occlusion: her birinde önce model, sonra iki uç profil
ortalaması. C4 kanal-kritiklik (occlusion−score) payload eksi platform,
sonra model ortalamasıdır. Beklenen yönler sırasıyla +,−,+,−'dir.
C1, aynı kritiklik vektörünün policy ve hedefte kullanıldığı yapısal kalibrasyon
tutarlılığıdır; açıklamaya özgü kazanım değildir. C2 bunun eşit-olay hedefindeki
maliyetini, C3 ham sapma ile occlusion kanıtı farkını, C4 profil etkileşimini
özetler. Hiçbiri fiziksel müdahale veya insan performansı etkisi değildir.

Ana beş-model ailede her kontrast 40 seed farkının ortalamasıdır; sample
SD ddof 1, df 39, iki taraflı %98.75 t aralığı kullanılır. Bonferroni aile
hata düzeyi 0.05'tir. Her kontrastın ortalama/SD/CI ve bütün seed değerleri
verilir. Sıfırı beklenen tarafta dışlama yön desteği; ters tarafta dışlama
ters yön desteği; sıfırı kapsama yön belirsizliğidir. Dördünün birlikte
beklenen yönü desteklemesi ayrıca raporlanır; tek olumlu sonuç seçilmez.

Altı-model duyarlılık ve tek-model aralıkları %95, düzeltilmemiş ve
betimseldir; doğrulanmış aileye yükseltilmez. Bütün 12 profil, üç hedef ve
altı policy hücresi korunur. Operasyonel SESOI kanıtı yoktur; pratik önem,
eşdeğerlik veya 100 alarm başına olay kazancı dönüşümü iddia edilmez.
40 seed seçimi eski n=10 plug-in SD precision planıdır; güç/precision
garantisi değildir. Geniş aralık daha fazla seed ekleme gerekçesi olmaz.
Ana beş-model ile altı-model duyarlılığında C1–C4 ortalama işaretleri ve yön
destek sınıflarının uyuşması ayrıca raporlanır; farklı CI düzeyleri açıkça
yazılır. Her seed/model kuyruğunun episode sayısı, model bazında min/medyan/max,
sıfır kapasite kuyrukları ve tekrarlı policy hücre sayıları ayrı saklanır.
Her hücrenin bütçe–utility eğrisi sonuç dosyasında korunur.

Tam 40 seed×6model×12profil×6policy×3hedef olmadan planlı aggregate
sertifikalanmaz. Eksik/bozuk hücre imputasyonu, başarısız seed değiştirme,
sonuçtan sonra aile/model/hiperparametre seçme yoktur. Geçerli negatif/null
etki teknik arıza değildir. Teknik arıza aynı seed ve aynı hashli kodla
kurtarılır; önceki tamamlanmış birimler tekrar koşulmaz.

## Dayanıklılık ve kapanış

400 atomik birim: her seed için gen, feat, altı model, cross ve policy.
Çıktı envanteri incelenecek JSON adayında exact kod hash'leriyle dondurulur.
Tek CPU worker, sayısal thread 1; 10 GiB boş disk, 3 GiB kullanılabilir RAM
rezervi ve child-tree 4 GiB RSS tavanı korunur. Birim timeout 900 s; bütün
koşunun süre tavanı ve crash/restart muhasebesi final JSON'da açık bağlanır.
CPU/RSS/phase/elapsed/completed-units/son checkpoint heartbeat'i 0.5s'dir.
İlk başlangıçtan 12 saatlik tavan kesinti süresini de içerir. Bu süre bir
tamamlanma garantisi değildir: mevcut discovery model süreleri dayanak olsa
da yeni policy fazının süresi bilinmiyor. Süre dolarsa tamamlanmış birimler
korunur ve otomatik baştan koşu yapılmaz; devam için prospective değişiklik,
bağımsız inceleme ve yeni public freeze gerekir. İlk gerçek harness hatasında
log ve kısmi çıktılar korunur; kod hash'i değişirse mevcut final sözleşmeyle
devam edilmez, başarısız seed sessizce değiştirilmez veya gizlenmez.

Resume exclusive lock altında hash/şema/binding doğrulanan tamamlanmış
birimleri atlamalıdır. Kısmi çıktılar silinmez, ayrı attempt'e alınır.
Aktif/orphan child kimliği belirsizken recovery launch reddedilmelidir.
Bu yükümlülükler hazırlık kodunun bağımsız incelemesinde somut testlere
bağlanır; yalnız toy lifecycle geçmesi bilimsel entegrasyon PASS'i değildir.

Evaluator bir fiziksel müdahale veya arıza önleme simülasyonu değildir;
politika yalnız donmuş alarm kuyruğunu sıralar. Schema-v3 multi-mode
averted-failure mekanizması bu nedenle uygulanamaz; gerekçe prospective
adayda taşınır. Kapsam kazanımı arıza önlenmiş gibi sayılmaz. Primary
başarısızlığında confirmatory rescue yasaktır; ana hüküm değişmez,
exploratory sonuç iddia düzeyini yükseltemez. Etik/lisans/sızıntı/geçersiz
veri/kaynak tavanı ile hash drift hard-stop'tur.
Kaynak/binding/schema/hash ve kaynak tavanı kontrolleri supervisor tarafından
mekanik uygulanır. Etik/lisans değişikliği veya mekanik kontrollerin dışında
sızıntı şüphesi operatörün durdurma yükümlülüğüdür; otomatik dedektör olduğu
iddia edilmez. Aday JSON bu iki türü işlev ve kayıt yollarıyla ayırır.

Kapanış candidate→independent review→decision→final gerçek hash ve zaman
zinciri, sonra prelaunch validator, sonra exact public önkayıt onayıdır.
Üretim sonrası bütün artifact/checkpoint/prediction/terminal kayıtları,
registry, timebase, durability ve bağımsız sonuç kontrolü final schema-v3
sertifikasına bağlanır. Prelaunch PASS bilimsel veya A–F PASS değildir.

## Kamuya açık idari yol gösterimi

Date/time: 2026-09-20T17:42:36.270501+00:00
Tool: Codex
Model: gpt-6-astra / xhigh
Operation ID: f07-mta-fresh-to-round-f-20260920

Yerel kullanıcı/çalışma kökleri kamuya açık metinde <experiment-home>, <author-profile> ve <controlled-workspace> olarak gösterilir. Özgün teknik makbuzlar hashli özel kayıtta korunur; deney veri, kod ve çıktılarının bilimsel içeriği değişmez. Supervisor ve owned wrapper onarımı priority alt yorumlayıcısını içermez; bu dar kapsam önceki incelemede nonblocking olarak değerlendirilmiş ve final ekinde açıklanmıştır. Merkez prelaunch makbuzu özel idari hash kanıtıdır, public byte döngüsünün parçası değildir.
