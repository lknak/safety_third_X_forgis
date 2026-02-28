import { Routes, Route, Navigate } from "react-router-dom";
import HomePage from "./pages/HomePage";
import LineCellsPage from "./pages/LineCellsPage";
import { RobotControlPage } from "./pages/RobotControlPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/line/:lineId" element={<LineCellsPage />} />
      <Route path="/line/:lineId/cell/:cellId" element={<RobotControlPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
