"""Ghép xe giữa các camera (theo đợt). Người phụ trách: Khiêm.

Đầu vào : các file JSON v1.0 của AI Engine (mỗi file = 1 video của 1 camera).
Đầu ra  : - mỗi tracklet một `global_id` (cùng global_id = cùng một xe ở nhiều camera);
          - danh sách ỨNG VIÊN chưa chắc chắn để người kiểm tra xác nhận / bác bỏ trên giao diện.

Thuật toán (giống bản đã đo trên CityFlow, IDF1 45–50):
 1. Cặp tracklet được xét khi: khác camera, cách nhau ≤ `max_gap_s` giây, qua hết các điều kiện phụ đang bật.
 2. Điểm của cặp = cosine giữa 2 vector FastReID (đã chuẩn hóa).
 3. Ghép tham lam từ cặp điểm cao xuống: gộp 2 nhóm nếu trung bình cosine mọi cặp chéo ≥ `thr_auto`,
    mọi cặp chéo đều hợp lệ, và nhóm mới không có 2 tracklet cùng camera.
 4. Cặp có điểm trong [`thr_candidate`, `thr_auto`), hoặc vượt ngưỡng nhưng thua sát nút một cặp khác,
    → đưa vào danh sách ứng viên.
 5. Quyết định của người kiểm tra (file decisions) được áp trước: "same" = bắt buộc ghép, "different" = cấm ghép.

Thông tin phụ (đều là công tắc trong config, mặc định chỉ bật loại xe 2 bánh / 4 bánh – các cái khác chưa đo):
 - type    : loại xe khác nhau thì không ghép ('coarse' = chỉ tách xe 2 bánh với xe 4 bánh; 'strict' = phải cùng loại).
 - plate   : 2 biển số đều đọc chắc (≥ plate_min_conf): giống nhau → cộng điểm (ghép được cả khi thiếu vector);
             khác nhau quá `plate_max_diff` ký tự → không ghép.
 - color   : 2 màu đều chắc (≥ color_min_conf) và khác nhóm → không ghép (trắng/bạc/xám coi là 1 nhóm).
 - links   : sơ đồ đường đi giữa camera: chỉ ghép A → B nếu có đường A → B và thời gian đi nằm trong [min_s, max_s]
             (tùy chọn kiểm tra cả cạnh ra của A / cạnh vào của B).
"""
import json
from datetime import datetime
from pathlib import Path
import numpy as np

DEFAULTS = {
    'thr_auto': 0.50,            # cosine ≥ ngưỡng này: tự ghép
    'thr_candidate': 0.40,       # cosine trong [thr_candidate, thr_auto): đưa vào danh sách ứng viên
    'ambiguous_margin': 0.05,    # cặp vượt ngưỡng nhưng kém cặp thắng < margin → cũng là ứng viên
    'max_candidates_per_tracklet': 3,
    'max_gap_s': 30,             # 2 tracklet cách nhau quá số giây này thì không xét
    'min_vector_crops': 1,       # bỏ vector tạo từ ít ảnh hơn số này
    'type': 'coarse',            # off | coarse | strict
    'plate': {'enabled': False, 'min_conf': 0.80, 'max_diff': 1, 'bonus': 0.30},
    'color': {'enabled': False, 'min_conf': 0.70,
              'groups': [['white', 'silver', 'gray'], ['black'], ['red', 'orange', 'brown'], ['yellow'],
                         ['green'], ['blue'], ['purple', 'pink']]},
    'links': {'enabled': False, 'allow_overlap': True, 'routes': []},
    # routes: [{from: CAM_A, to: CAM_B, min_s: 5, max_s: 60, exit_edge: right, entry_edge: left, dwell_s: 30}, ...]
    # (đường qua camera trung gian A→B→C tự suy ra; dwell_s = thời gian tối đa xe ở trong khung camera giữa)
}

TWO_WHEEL = {'motorcycle'}
FOUR_WHEEL = {'car', 'bus', 'truck'}


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def load_tracklets(paths):
    """Đọc các file JSON v1.0 → danh sách tracklet phẳng (mỗi tracklet thêm camera_id, video_id, t0, t1 dạng giây)."""
    TL = []
    for p in paths:
        d = json.load(open(p, encoding='utf-8'))
        assert d.get('schema_version') == '1.0', f'{p}: không phải JSON v1.0'
        cam, vid = d['video']['camera_id'], d['video']['video_id']
        for t in d['tracklets']:
            e = next((x for x in t.get('embeddings') or []), None)
            TL.append({**{k: t.get(k) for k in ('tracklet_id', 'vehicle_type', 'color', 'color_conf', 'plate_text',
                                                 'plate_conf', 'entry_edge', 'exit_edge', 'crop_file', 'is_moving')},
                       'camera_id': cam, 'video_id': vid, 'src': str(p),
                       't_start': t['t_start'], 't_end': t['t_end'],
                       't0': datetime.fromisoformat(t['t_start']).timestamp(),
                       't1': datetime.fromisoformat(t['t_end']).timestamp(),
                       'vec': np.asarray(e['vector'], np.float32) if e else None,
                       'n_crops': e.get('n_crops', 0) if e else 0})
    return TL


def _edit(a, b):
    """Số ký tự khác nhau tối thiểu (Levenshtein) giữa 2 biển số."""
    p = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        q = [i]
        for j, cb in enumerate(b, 1):
            q.append(min(p[j] + 1, q[j - 1] + 1, p[j - 1] + (ca != cb)))
        p = q
    return p[-1]


class Matcher:
    def __init__(self, cfg=None):
        self.c = _merge(DEFAULTS, cfg or {})
        g = self.c['color']['groups']
        self.color_group = {col: i for i, grp in enumerate(g) for col in grp}
        self.routes = self._closure(self.c['links']['routes'])

    @staticmethod
    def _closure(routes, max_hops=4):
        """Thêm đường đi qua camera trung gian: A→B (5–25 s) + B→C (5–25 s) ⇒ A→C (10–50 s + thời gian ở B).
        Cần vì 1 xe đã ghép A, B, C thì cặp A–C cũng phải hợp lệ. Cạnh ra/vào giữ theo đoạn đầu/cuối."""
        R = [dict(r, hops=1) for r in routes]; base = list(R)
        for _ in range(max_hops - 1):
            new = []
            for r1 in R:
                for r2 in base:
                    if r1['to'] == r2['from'] and r2['to'] != r1['from'] and r1['hops'] < max_hops:
                        new.append({'from': r1['from'], 'to': r2['to'], 'hops': r1['hops'] + 1,
                                    'min_s': r1.get('min_s', 0) + r2.get('min_s', 0),
                                    'max_s': r1.get('max_s', 1e9) + r2.get('max_s', 1e9) + r2.get('dwell_s', 30),
                                    'exit_edge': r1.get('exit_edge'), 'entry_edge': r2.get('entry_edge')})
            keys = {(r['from'], r['to'], r['hops']) for r in R}
            new = [r for r in new if (r['from'], r['to'], r['hops']) not in keys]
            if not new:
                break
            R += new
        return R

    # ---------- điều kiện từng cặp ----------
    def _type_ok(self, a, b):
        m, ta, tb = self.c['type'], a['vehicle_type'], b['vehicle_type']
        if m == 'off' or 'unknown' in (ta, tb) or 'other' in (ta, tb):
            return True
        if m == 'strict':
            return ta == tb
        return not ((ta in TWO_WHEEL and tb in FOUR_WHEEL) or (tb in TWO_WHEEL and ta in FOUR_WHEEL))

    def _plate(self, a, b):
        """+1 = biển chắc chắn giống, -1 = chắc chắn khác, 0 = không đủ thông tin."""
        p = self.c['plate']
        if not p['enabled']:
            return 0
        pa, pb = a.get('plate_text'), b.get('plate_text')
        if not pa or not pb or (a.get('plate_conf') or 0) < p['min_conf'] or (b.get('plate_conf') or 0) < p['min_conf']:
            return 0
        if pa == pb:
            return 1
        return -1 if _edit(pa, pb) > p['max_diff'] else 0

    def _color_ok(self, a, b):
        p = self.c['color']
        if not p['enabled'] or not a.get('color') or not b.get('color'):
            return True
        if (a.get('color_conf') or 0) < p['min_conf'] or (b.get('color_conf') or 0) < p['min_conf']:
            return True
        ga, gb = self.color_group.get(a['color'], a['color']), self.color_group.get(b['color'], b['color'])
        return ga == gb

    def _link_ok(self, a, b):
        L = self.c['links']
        if not L['enabled']:
            return True
        if min(a['t1'], b['t1']) - max(a['t0'], b['t0']) > 0:          # 2 camera cùng thấy xe một lúc
            return bool(L['allow_overlap']) and any({r['from'], r['to']} == {a['camera_id'], b['camera_id']} for r in self.routes)
        if a['t0'] > b['t0']:
            a, b = b, a                                                 # a đi trước
        gap = b['t0'] - a['t1']
        for r in self.routes:
            if r['from'] == a['camera_id'] and r['to'] == b['camera_id'] and r.get('min_s', 0) <= gap <= r.get('max_s', 1e9):
                if r.get('exit_edge') and a.get('exit_edge') not in (r['exit_edge'], 'inside'):
                    continue
                if r.get('entry_edge') and b.get('entry_edge') not in (r['entry_edge'], 'inside'):
                    continue
                return True
        return False

    def pair_reason(self, a, b):
        """None nếu cặp hợp lệ, không thì lý do bị loại."""
        if a['camera_id'] == b['camera_id']:
            return 'cùng camera'
        gap = max(0.0, b['t0'] - a['t1'], a['t0'] - b['t1'])
        if gap > self.c['max_gap_s']:
            return f'cách {gap:.0f}s'
        if not self._type_ok(a, b):
            return 'khác loại xe'
        if self._plate(a, b) < 0:
            return 'khác biển số'
        if not self._color_ok(a, b):
            return 'khác màu'
        if not self._link_ok(a, b):
            return 'không có đường đi giữa 2 camera'
        return None

    # ---------- ghép ----------
    def run(self, TL, decisions=None):
        c, N = self.c, len(TL)
        ids = [t['tracklet_id'] for t in TL]; pos = {k: i for i, k in enumerate(ids)}
        cam = np.array([t['camera_id'] for t in TL])
        has = np.array([t['vec'] is not None and t['n_crops'] >= c['min_vector_crops'] for t in TL])
        dim = next((len(t['vec']) for t in TL if t['vec'] is not None), 1)
        V = np.stack([t['vec'] if h else np.zeros(dim, np.float32) for t, h in zip(TL, has)]) if N else np.zeros((0, dim))
        S = V @ V.T
        S[~has, :] = np.nan; S[:, ~has] = np.nan                         # không có vector: chưa biết điểm
        OK = np.zeros((N, N), bool); WHY = {}
        for i in range(N):
            for j in range(i + 1, N):
                r = self.pair_reason(TL[i], TL[j])
                OK[i, j] = OK[j, i] = r is None
                if r is None and self._plate(TL[i], TL[j]) > 0:          # biển số chắc chắn giống: cộng điểm
                    S[i, j] = S[j, i] = min(1.0, (S[i, j] if not np.isnan(S[i, j]) else c['thr_auto']) + c['plate']['bonus'])
                    WHY[(i, j)] = 'biển số giống'
        # quyết định của người kiểm tra
        must, cannot = [], set()
        for d in decisions or []:
            i, j = pos.get(d['tracklet_a']), pos.get(d['tracklet_b'])
            if i is None or j is None:
                continue
            if d['decision'] == 'same':
                must.append((i, j))
            elif d['decision'] == 'different':
                OK[i, j] = OK[j, i] = False; cannot.add((min(i, j), max(i, j)))
        owner = list(range(N)); mem = {i: [i] for i in range(N)}; method = {}

        def mean_s(ma, mb):
            x = S[np.ix_(ma, mb)]
            return float(np.nanmean(x)) if np.isfinite(x).any() else np.nan

        def join(A, B, how):
            for x in mem[B]:
                owner[x] = A
            mem[A] = mem[A] + mem[B]; del mem[B]; method[A] = how

        for i, j in must:                                                # người đã xác nhận: ghép trước, không xét ngưỡng
            A, B = owner[i], owner[j]
            if A != B and not (set(cam[mem[A]]) & set(cam[mem[B]])):
                join(A, B, 'người xác nhận')
        iu = np.triu_indices(N, 1)
        sv = np.nan_to_num(S[iu], nan=-1)
        sel = OK[iu] & (sv >= c['thr_candidate'])
        pairs = sorted(zip(sv[sel], iu[0][sel], iu[1][sel]), reverse=True)
        lost = []                                                        # cặp vượt ngưỡng nhưng không được ghép
        for s, i, j in pairs:
            if s < c['thr_auto']:
                break
            A, B = owner[i], owner[j]
            if A == B:
                continue
            ma, mb = mem[A], mem[B]
            if set(cam[ma]) & set(cam[mb]) or not OK[np.ix_(ma, mb)].all():
                lost.append((s, i, j)); continue
            m = mean_s(ma, mb)
            if not np.isnan(m) and m < c['thr_auto']:
                lost.append((s, i, j)); continue
            join(A, B, WHY.get((i, j), 'vector'))
        # danh sách ứng viên
        best = {}                                                        # điểm cao nhất của mỗi tracklet với tracklet đã ghép cùng nhóm
        for g in mem.values():
            for x in g:
                o = [S[x, y] for y in g if y != x and not np.isnan(S[x, y])]
                best[x] = max(o) if o else None
        cand, per = [], {}
        for s, i, j in pairs:
            if owner[i] == owner[j]:
                continue
            if s >= c['thr_auto']:
                bi, bj = best.get(i), best.get(j)
                close = any(b is not None and b - s < c['ambiguous_margin'] for b in (bi, bj)) or (bi is None and bj is None)
                if not close:
                    continue
                kind = 'vượt ngưỡng nhưng không ghép được (xung đột với cặp khác)'
            else:
                kind = 'điểm sát ngưỡng'
            if per.get(i, 0) >= c['max_candidates_per_tracklet'] or per.get(j, 0) >= c['max_candidates_per_tracklet']:
                continue
            per[i] = per.get(i, 0) + 1; per[j] = per.get(j, 0) + 1
            a, b = (TL[i], TL[j]) if TL[i]['t0'] <= TL[j]['t0'] else (TL[j], TL[i])
            cand.append({'tracklet_a': a['tracklet_id'], 'tracklet_b': b['tracklet_id'], 'src_a': a.get('src'), 'src_b': b.get('src'),
                         'camera_a': a['camera_id'], 'camera_b': b['camera_id'],
                         'crop_a': a['crop_file'], 'crop_b': b['crop_file'],
                         'score': round(float(s), 4), 'gap_s': round(max(0.0, b['t0'] - a['t1']), 1),
                         'vehicle_type': [a['vehicle_type'], b['vehicle_type']],
                         'plate': [a['plate_text'], b['plate_text']], 'color': [a['color'], b['color']],
                         'kind': kind, 'global_id_a': None, 'global_id_b': None, 'status': 'pending'})
        # đánh số global_id: nhóm xuất hiện sớm hơn được số nhỏ hơn
        groups = sorted(mem.values(), key=lambda g: min(TL[x]['t0'] for x in g))
        gid_of, vehicles = {}, []
        for k, g in enumerate(groups, 1):
            g = sorted(g, key=lambda x: TL[x]['t0']); gid = f'G{k:06d}'
            for x in g:
                gid_of[ids[x]] = gid
            sc = [S[x, y] for x in g for y in g if x < y and not np.isnan(S[x, y])]
            types = [TL[x]['vehicle_type'] for x in g]
            plates = [TL[x]['plate_text'] for x in g if TL[x]['plate_text']]
            vehicles.append({'global_id': gid, 'tracklets': [ids[x] for x in g], 'cameras': [str(cam[x]) for x in g],
                             't_first': TL[g[0]]['t_start'], 't_last': TL[g[-1]]['t_end'],
                             'vehicle_type': max(set(types), key=types.count),
                             'plate_text': max(set(plates), key=plates.count) if plates else None,
                             'min_score': round(float(min(sc)), 4) if sc else None,
                             'method': method.get(owner[g[0]]) if len(g) > 1 else 'một camera'})
        for cd in cand:
            cd['global_id_a'], cd['global_id_b'] = gid_of[cd['tracklet_a']], gid_of[cd['tracklet_b']]
        multi = [v for v in vehicles if len(v['cameras']) > 1]
        summary = {'tracklets': N, 'co_vector': int(has.sum()), 'xe': len(vehicles), 'xe_qua_nhieu_camera': len(multi),
                   'ung_vien': len(cand), 'quyet_dinh_da_ap': len(must) + len(cannot)}
        return {'schema': 'match-1.0', 'created_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                'params': self.c, 'summary': summary, 'vehicles': vehicles, 'tracklet_to_global': gid_of,
                'candidates': cand}


def _crop(src, crop_file, cache):
    """Lấy ảnh crop từ <json>_crops.zip nằm cạnh file JSON (không có thì None)."""
    import zipfile, cv2
    if not src or not crop_file:
        return None
    zp = Path(src).with_name(Path(src).stem + '_crops.zip')
    if zp not in cache:
        cache[zp] = zipfile.ZipFile(zp) if zp.exists() else None
    z = cache[zp]
    if z is None or crop_file not in z.namelist():
        return None
    return cv2.imdecode(np.frombuffer(z.read(crop_file), np.uint8), cv2.IMREAD_COLOR)


def candidate_sheet(cands, path, cell=200, max_rows=60):
    """Bảng ảnh cho người kiểm tra: mỗi dòng = 1 cặp ứng viên (ảnh A | ảnh B | điểm, khoảng cách thời gian)."""
    import cv2
    rows, cache = [], {}
    for k, c in enumerate(cands[:max_rows]):
        row = np.full((cell + 30, 2 * cell + 10, 3), 255, np.uint8)
        for side, (src, cf) in enumerate([(c.get('src_a'), c['crop_a']), (c.get('src_b'), c['crop_b'])]):
            im = _crop(src, cf, cache)
            if im is not None:
                h, w = im.shape[:2]; s = cell / max(h, w); im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))))
                x0 = side * (cell + 10); row[30:30 + im.shape[0], x0:x0 + im.shape[1]] = im
        cv2.putText(row, f"#{k} cos {c['score']:.2f}  cach {c['gap_s']:.0f}s  {c['camera_a'][-12:]} > {c['camera_b'][-12:]}",
                    (4, 20), 0, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        rows.append(row)
    if not rows:
        return None
    cols = 3; blank = np.full_like(rows[0], 255)
    rows += [blank] * (-len(rows) % cols)
    grid = np.vstack([np.hstack(rows[i:i + cols]) for i in range(0, len(rows), cols)])
    cv2.imwrite(str(path), grid); return path


def write_outputs(res, out_dir, name):
    """Ghi JSON kết quả + 2 file CSV dễ xem (xe qua nhiều camera, danh sách ứng viên) + bảng ảnh ứng viên."""
    import pandas as pd
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    js = out / f'{name}.json'
    json.dump(res, open(js, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    pd.DataFrame([{**v, 'tracklets': ' | '.join(v['tracklets']), 'cameras': ' > '.join(v['cameras'])}
                  for v in res['vehicles'] if len(v['cameras']) > 1]).to_csv(out / f'{name}_vehicles.csv', index=False)
    flat = lambda x: ' / '.join('-' if y is None else str(y) for y in x)
    cols = ['tracklet_a', 'tracklet_b', 'score', 'gap_s', 'camera_a', 'camera_b', 'vehicle_type', 'plate', 'color', 'kind',
            'global_id_a', 'global_id_b', 'status']
    pd.DataFrame([{k: flat(c[k]) if isinstance(c[k], list) else c[k] for k in cols} for c in res['candidates']],
                 columns=cols).to_csv(out / f'{name}_candidates.csv', index=False)
    candidate_sheet(res['candidates'], out / f'{name}_candidates.jpg')
    return js
