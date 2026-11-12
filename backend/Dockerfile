# KlickLab API 서버 (Spring Boot). 빌드 컨텍스트는 backend/ 이다.
#   docker build -t klicklab-backend backend

FROM eclipse-temurin:21-jdk AS build
WORKDIR /src

# 의존성을 먼저 받아 소스가 바뀌어도 캐시가 유지되게 한다
COPY gradlew settings.gradle build.gradle ./
COPY gradle ./gradle
# Windows 체크아웃(autocrlf)의 CRLF 가 셔뱅을 깨뜨리지 않게 한다
RUN sed -i 's/\r$//' gradlew && chmod +x gradlew && ./gradlew --no-daemon dependencies > /dev/null

COPY src ./src
RUN ./gradlew --no-daemon bootJar -x test \
    && cp "$(ls build/libs/*.jar | grep -v -- '-plain' | head -n 1)" /app.jar

FROM eclipse-temurin:21-jre-alpine
RUN addgroup -S klicklab && adduser -S -G klicklab -u 10001 klicklab
WORKDIR /app
COPY --from=build --chown=klicklab:klicklab /app.jar ./app.jar
USER klicklab

# 4000 은 API(PORT 로 변경), 9091 은 Actuator(/health, /metrics)
EXPOSE 4000 9091
HEALTHCHECK --interval=10s --timeout=3s --start-period=40s --retries=10 \
  CMD wget -qO- http://127.0.0.1:9091/health | grep -q UP || exit 1

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
