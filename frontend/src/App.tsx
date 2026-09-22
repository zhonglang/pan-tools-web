import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Button, Layout, Typography } from "antd";
import { api, type User } from "./api";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import AdminUsersPage from "./pages/AdminUsersPage";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  function onAuthenticated(next: User) {
    setUser(next);
  }

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Typography.Text style={{ color: "white" }}>网盘工具</Typography.Text>
        {user ? (
          <Button
            onClick={async () => {
              await api.logout();
              setUser(null);
              navigate("/login");
            }}
          >
            退出
          </Button>
        ) : null}
      </Layout.Header>
      <Layout.Content>
        <Routes>
          <Route path="/login" element={<LoginPage onAuthenticated={onAuthenticated} />} />
          <Route path="/register" element={<RegisterPage onAuthenticated={onAuthenticated} />} />
          <Route
            path="/admin/users"
            element={
              loading ? (
                <Typography.Paragraph style={{ padding: 24 }}>加载中</Typography.Paragraph>
              ) : user?.role === "admin" ? (
                <AdminUsersPage />
              ) : (
                <Navigate to="/login" />
              )
            }
          />
          <Route path="/" element={<Typography.Paragraph style={{ padding: 24 }}>{user ? `已登录：${user.email}（${user.effective_plan}）` : "请登录"}</Typography.Paragraph>} />
        </Routes>
      </Layout.Content>
    </Layout>
  );
}
