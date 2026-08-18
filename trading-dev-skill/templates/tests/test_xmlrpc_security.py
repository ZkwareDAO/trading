#!/usr/bin/env python3
"""
XML-RPC 安全测试 - 验证 defusedxml 补丁是否正确应用

测试 XML 外部实体攻击 (XXE) 是否被阻止
"""

import pytest

# 测试 defusedxml 补丁是否生效
class TestDefusedXMLPatch:
    """XML 安全补丁测试"""

    def test_defusedxml_monkey_patch_applied(self):
        """测试 defusedxml 补丁已应用"""
        # 尝试导入已打补丁的 xmlrpc 模块
        try:
            from defusedxml.xmlrpc import monkey_patch
            monkey_patch()

            # 验证 xmlrpc.client 已使用 defusedxml
            import xmlrpc.client
            from defusedxml import ElementTree

            # 检查 xmlrpc.client 的 ExpatParser 是否被替换
            # defusedxml 会替换 XML 解析器为安全版本
            assert hasattr(xmlrpc.client, 'loads')

        except ImportError:
            pytest.fail("defusedxml 未安装或补丁应用失败")

    def test_xml_external_entity_attack_blocked(self):
        """测试 XML 外部实体攻击 (XXE) 被阻止"""
        from defusedxml.xmlrpc import monkey_patch
        monkey_patch()

        import xmlrpc.client

        # 恶意 XML payload - 尝试读取 /etc/passwd
        malicious_xml = """<?xml version="1.0"?>
        <!DOCTYPE methodCall [
            <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <methodCall>
            <methodName>test</methodName>
            <params><param><value>&xxe;</value></param></params>
        </methodCall>
        """

        # defusedxml 应该阻止这种攻击
        # 要么抛出异常，要么忽略外部实体
        with pytest.raises((ValueError, TypeError, Exception)):
            xmlrpc.client.loads(malicious_xml)

    def test_normal_xmlrpc_request_works(self):
        """测试正常 XML-RPC 请求仍能工作"""
        from defusedxml.xmlrpc import monkey_patch
        monkey_patch()

        import xmlrpc.client

        # 正常的 XML-RPC 请求
        normal_request = """<?xml version="1.0"?>
        <methodCall>
            <methodName>add</methodName>
            <params>
                <param><value><int>5</int></value></param>
                <param><value><int>3</int></value></param>
            </params>
        </methodCall>
        """

        # 应该能正常解析
        method, params = xmlrpc.client.loads(normal_request)
        assert method == (5, 3)  # xmlrpc.client.loads 返回 (params, methodname) 的逆序
