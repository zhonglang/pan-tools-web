import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type User } from "../api";
import AuthFrame from "../components/AuthFrame";

type RegisterPageProps = {
  onAuthenticated: (user: User) => void;
};

export default function RegisterPage({ onAuthenticated }: RegisterPageProps) {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setPending(true);
    setError("");
    try {
      const user = await api.register(email, password);
      onAuthenticated(user);
      navigate("/accounts");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "注册失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthFrame title="创建账号" subtitle="注册后默认为免费会员。付费等级由管理员开通。">
      <form className="space-y-4" onSubmit={onSubmit}>
        <label className="block text-[13px] font-medium text-ink/80">
          邮箱
          <input name="email" type="email" required autoComplete="email" placeholder="you@example.com" className="field" />
        </label>
        <label className="block text-[13px] font-medium text-ink/80">
          密码
          <input
            name="password"
            type="password"
            required
            minLength={8}
            maxLength={128}
            autoComplete="new-password"
            placeholder="8 到 128 位"
            className="field"
          />
        </label>
        {error ? <p className="alert">{error}</p> : null}
        <button type="submit" disabled={pending} className="btn btn-primary w-full">
          {pending ? "正在创建" : "注册并进入"}
        </button>
      </form>
      <p className="mt-8 text-sm text-ink/55">
        已有账号？{" "}
        <Link to="/login" className="font-bold text-primary-dark hover:text-primary">
          去登录
        </Link>
      </p>
    </AuthFrame>
  );
}
