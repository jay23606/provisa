package io.provisa.jdbc;

import org.junit.jupiter.api.Test;

import java.sql.DriverPropertyInfo;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.*;

class ProvisaDriverTest {

    private final ProvisaDriver driver = new ProvisaDriver();

    @Test
    void acceptsValidUrl() {
        assertTrue(driver.acceptsURL("jdbc:provisa://localhost:8001"));
    }

    @Test
    void rejectsNullUrl() {
        assertFalse(driver.acceptsURL(null));
    }

    @Test
    void rejectsOtherDriverUrl() {
        assertFalse(driver.acceptsURL("jdbc:postgresql://localhost:5432/test"));
    }

    @Test
    void acceptsUrlWithParameters() {
        assertTrue(driver.acceptsURL("jdbc:provisa://localhost:8001?role=analyst"));
    }

    @Test
    void propertyInfoListsTheConnectionProperties() {
        DriverPropertyInfo[] props = driver.getPropertyInfo("jdbc:provisa://localhost:8001", new Properties());
        assertEquals(4, props.length);
        assertEquals("flight_port", props[3].name);
        assertEquals("role", props[2].name);
    }

    @Test
    void versionNumbers() {
        assertEquals(0, driver.getMajorVersion());
        assertEquals(2, driver.getMinorVersion());
        assertFalse(driver.jdbcCompliant());
    }
}
