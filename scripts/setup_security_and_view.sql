-- Executed by bootstrap_resources inside the configured project database.
-- Login creation and secret handling are performed by the administrative bootstrap.
IF DB_NAME() NOT LIKE 'cold[_]chain[_]claude[_]mcp%'
    THROW 51000, 'Refusing to configure a database outside this project.', 1;
IF SCHEMA_ID('FDE_VIEWS') IS NULL EXEC('CREATE SCHEMA FDE_VIEWS');
GO
CREATE OR ALTER VIEW FDE_VIEWS.VW_ACTIVE_FLEET AS
SELECT TS_UTC AS [Timestamp], V_LAT AS Latitude, V_LON AS Longitude,
    CAST(IOT_TEMP_VAL_C AS FLOAT) AS Current_Temperature_C,
    CGO_COND_CD AS Cargo_Condition_Code, RISK_CLS_TXT AS Risk_Classification,
    DELAY_PROB_DEC AS Delay_Probability, PRT_CNG_LVL AS Port_Congestion_Level,
    RT_RSK_IDX AS Route_Risk_Index
FROM dbo.TBL_SC_FLEET_HIST_RAW;
GO
IF DATABASE_PRINCIPAL_ID('USR_CC_CLAUDE_RO') IS NULL
    CREATE USER USR_CC_CLAUDE_RO FOR LOGIN USR_CC_CLAUDE_RO;
GRANT SELECT ON FDE_VIEWS.VW_ACTIVE_FLEET TO USR_CC_CLAUDE_RO;
DENY SELECT ON dbo.TBL_SC_FLEET_HIST_RAW TO USR_CC_CLAUDE_RO;
DENY INSERT, UPDATE, DELETE, ALTER ON SCHEMA::dbo TO USR_CC_CLAUDE_RO;
IF OBJECT_ID('FDE_VIEWS.AgentAuditLog','U') IS NULL
    CREATE TABLE FDE_VIEWS.AgentAuditLog (
        LogID INT IDENTITY(1,1) PRIMARY KEY,
        Timestamp DATETIME2 DEFAULT SYSUTCDATETIME(),
        SessionID VARCHAR(50), NodeExecuted VARCHAR(50),
        ToolName VARCHAR(100), Content NVARCHAR(MAX)
    );
GRANT INSERT ON FDE_VIEWS.AgentAuditLog TO USR_CC_CLAUDE_RO;
DENY SELECT, UPDATE, DELETE, ALTER ON FDE_VIEWS.AgentAuditLog TO USR_CC_CLAUDE_RO;
GO
