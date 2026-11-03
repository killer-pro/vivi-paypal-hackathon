import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Landing from "./pages/Landing";
import Costs from "./pages/Costs";
import Credits from "./pages/Credits";
import CustomerDetail from "./pages/CustomerDetail";
import Customers from "./pages/Customers";
import ForgotPassword from "./pages/ForgotPassword";
import Login from "./pages/Login";
import Plan from "./pages/Plan";
import NewVideo from "./pages/NewVideo";
import Music from "./pages/Music";
import Studio from "./pages/Studio";
import Pricing from "./pages/Pricing";
import Projects from "./pages/Projects";
import Providers from "./pages/Providers";
import Register from "./pages/Register";
import ResetPassword from "./pages/ResetPassword";
import Verify from "./pages/Verify";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/verify" element={<Verify />} />
        <Route path="/forgot" element={<ForgotPassword />} />
        <Route path="/reset" element={<ResetPassword />} />
        <Route path="/decouvrir" element={<Landing />} />
        <Route element={<Layout />}>
          <Route index element={<Projects />} />
          <Route path="new" element={<NewVideo />} />
          <Route path="projects/:id" element={<Studio />} />
          <Route path="projects/:id/plan" element={<Plan />} />
          <Route path="music" element={<Music />} />
          <Route path="providers" element={<Providers />} />
          <Route path="costs" element={<Costs />} />
          <Route path="credits" element={<Credits />} />
          <Route path="clients" element={<Customers />} />
          <Route path="clients/:id" element={<CustomerDetail />} />
          <Route path="pricing" element={<Pricing />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
