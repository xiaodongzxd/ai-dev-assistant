"""
模拟特斯拉 Fleet API 的常用端点，返回车辆信息、驾驶状态、附近充电站等假数据。
用于演示 Data Agent 如何与外部 API 交互，无需真实账号。
"""

import random
from typing import Dict, List


class MockTeslaAPI:
    def __init__(self):
        self.vehicles = self._generate_vehicles(5)

    def _generate_vehicles(self, count: int) -> List[Dict]:
        """生成模拟车辆列表"""
        vehicles = []
        for i in range(count):
            vehicles.append({
                "id": i + 1000,
                "vin": f"5YJ3E{random.randint(100000, 999999)}",
                "display_name": f"Model 3 #{i + 1}",
                "state": "online",
                "software_version": "v12.5.4",
                "battery_level": random.randint(20, 100),
                "range_km": random.randint(200, 500),
            })
        return vehicles

    def get_vehicles(self) -> Dict:
        """GET /api/1/vehicles 返回所有车辆"""
        return {"response": self.vehicles}

    def get_vehicle_data(self, vehicle_id: int) -> Dict:
        """GET /api/1/vehicles/{id}/data 返回指定车辆的详细数据"""
        vehicle = next((v for v in self.vehicles if v["id"] == vehicle_id), None)
        if not vehicle:
            return {"error": "vehicle not found"}
        return {
            "response": {
                "vehicle": vehicle,
                "drive_state": {
                    "latitude": 37.7749 + random.uniform(-0.1, 0.1),
                    "longitude": -122.4194 + random.uniform(-0.1, 0.1),
                    "speed": random.randint(0, 120),
                },
                "climate_state": {
                    "inside_temp": random.uniform(15, 30),
                    "outside_temp": random.uniform(5, 40),
                }
            }
        }

    def wake_up(self, vehicle_id: int) -> Dict:
        """POST /api/1/vehicles/{id}/wake_up 唤醒车辆"""
        return {"response": {"state": "online"}}

    def get_nearby_charging_sites(self, lat: float, lng: float) -> Dict:
        """GET /api/1/vehicles/{id}/nearby_charging_sites 模拟附近充电站"""
        return {
            "response": {
                "superchargers": [
                    {"name": f"Supercharger {i}", "distance_km": random.uniform(0.5, 10)}
                    for i in range(1, 4)
                ]
            }
        }


# 全局单例
_mock_tesla = None


def get_mock_tesla_api() -> MockTeslaAPI:
    global _mock_tesla
    if _mock_tesla is None:
        _mock_tesla = MockTeslaAPI()
    return _mock_tesla
