import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function SettingsPage() {
  const [baiduPassword, setBaiduPassword] = useState("");
  const [quarkPassword, setQuarkPassword] = useState("");
  const [xunleiPassword, setXunleiPassword] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .sharePasswords()
      .then((row) => {
        setBaiduPassword(row.baidu_password ?? "");
        setQuarkPassword(row.quark_password ?? "");
        setXunleiPassword(row.xunlei_password ?? "");
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
  }, []);

  async function submit() {
    setPending(true);
    setError("");
    setSaved("");
    try {
      const row = await api.saveSharePasswords(baiduPassword, quarkPassword, xunleiPassword);
      setBaiduPassword(row.baidu_password ?? "");
      setQuarkPassword(row.quark_password ?? "");
      setXunleiPassword(row.xunlei_password ?? "");
      setSaved("已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader
        title="系统配置"
        description="为百度网盘和夸克网盘设置批量分享的默认提取码。留空表示还没有默认值，创建加密链接时再填写。迅雷的提取码由网盘自动生成，并写在分享链接里。"
      />
      {error ? <p className="alert mb-4">{error}</p> : null}
      {saved ? <p className="mb-4 text-sm text-[#067647]">{saved}</p> : null}
      <form
        className="space-y-5 rounded-2xl border border-line bg-white p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="block text-sm">
          <span className="font-medium text-ink">百度网盘默认提取码</span>
          <input
            className="mt-2 h-10 w-full rounded-xl border border-line bg-white px-3"
            value={baiduPassword}
            maxLength={4}
            placeholder="4 位字母或数字"
            aria-label="百度网盘默认提取码"
            disabled={loading}
            onChange={(event) => setBaiduPassword(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-ink">夸克网盘默认提取码</span>
          <input
            className="mt-2 h-10 w-full rounded-xl border border-line bg-white px-3"
            value={quarkPassword}
            maxLength={4}
            placeholder="4 位字母或数字"
            aria-label="夸克网盘默认提取码"
            disabled={loading}
            onChange={(event) => setQuarkPassword(event.target.value)}
          />
        </label>
        <button type="submit" className="btn btn-primary disabled:opacity-50" disabled={pending || loading}>
          {pending ? "正在保存" : "保存"}
        </button>
      </form>
    </div>
  );
}
