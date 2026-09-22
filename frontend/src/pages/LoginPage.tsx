import { Button, Form, Input, Typography, message } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

export default function LoginPage() {
  const navigate = useNavigate();
  return (
    <Form
      style={{ maxWidth: 360, margin: "80px auto" }}
      onFinish={async (values: { email: string; password: string }) => {
        try {
          const user = await api.login(values.email, values.password);
          navigate(user.role === "admin" ? "/admin/users" : "/");
        } catch (error) {
          message.error(error instanceof Error ? error.message : "登录失败");
        }
      }}
    >
      <Typography.Title level={3}>登录</Typography.Title>
      <Form.Item name="email" rules={[{ required: true, type: "email" }]}>
        <Input placeholder="邮箱" />
      </Form.Item>
      <Form.Item name="password" rules={[{ required: true, min: 8 }]}>
        <Input.Password placeholder="密码" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block>
        登录
      </Button>
      <Link to="/register">注册</Link>
    </Form>
  );
}
