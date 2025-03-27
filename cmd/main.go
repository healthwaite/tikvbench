package main

import (
	"bufio"
	"flag"
	"fmt"
	"io/ioutil"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/sourcegraph/conc/pool"
)

const (
	READ_IDX   = 0
	INSERT_IDX = 1
	UPDATE_IDX = 2
	DELETE_IDX = 3
	MAX_OPS    = 4
)

type csv struct {
	benchName    string
	readRps      int
	readAveLat   float64
	readP50Lat   float64
	readP90Lat   float64
	readP99Lat   float64
	updateRps    int
	updateAveLat float64
	updateP50Lat float64
	updateP90Lat float64
	updateP99Lat float64
}

func mustInt(str string) int {
	i, err := strconv.Atoi(str)
	if err != nil {
		panic(fmt.Sprintf("failed to parse string (%s) into integer"))
	}
	return i
}
func opAsString(op int) string {
	switch op {
	case READ_IDX:
		return "READ"
	case INSERT_IDX:
		return "INSERT"
	case UPDATE_IDX:
		return "UPDATE"
	case DELETE_IDX:
		return "DELETE"
	default:
		panic("bad op type")
	}

}

type Results struct {
	Latencies  [MAX_OPS][]int
	Timestamps [MAX_OPS][]int
	NumErrors  [MAX_OPS]int
}

func sortAndTrim(timestamps []int, percentage int) []int {
	sort.Ints(timestamps)
	idx := (len(timestamps) * percentage) / 100
	endIdx := len(timestamps) - idx
	return timestamps[idx:endIdx]
}

func percentile(nums []int, perc int) int {
	if len(nums) == 0 {
		return -1
	}
	n := (len(nums) * perc) / 100
	return nums[n]
}

func average(nums []int) int {
	count := 0
	for _, n := range nums {
		count += n
	}

	return count / len(nums)
}

func parseResultsFile(filePath string) (*Results, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to open file %s: %w", filePath, err)
	}
	defer file.Close()

	results := &Results{}
	scanner := bufio.NewScanner(file)

	numLines := 0
	for scanner.Scan() {
		numLines += 1
		line := scanner.Text()
		if numLines == 1 {
			continue
		}

		fields := strings.Split(line, ",")
		if len(fields) != 3 {
			continue // Skip malformed lines
		}

		key := fields[0]
		timestamp, err := strconv.Atoi(fields[1])
		if err != nil {
			return nil, fmt.Errorf("invalid count in file %s: %w", filePath, err)
		}

		latency, err := strconv.Atoi(fields[2])
		if err != nil {
			return nil, fmt.Errorf("invalid value in file %s: %w", filePath, err)
		}

		idx := -1
		isError := false
		switch key {
		case "READ":
			idx = READ_IDX
		case "READ_ERROR":
			idx = READ_IDX
			isError = true
		case "INSERT":
			idx = INSERT_IDX
		case "INSERT_ERROR":
			idx = INSERT_IDX
			isError = true
		case "UPDATE":
			idx = UPDATE_IDX
		case "UPDATE_ERROR":
			idx = UPDATE_IDX
			isError = true
		case "DELETE":
			idx = DELETE_IDX
		case "DELETE_ERROR":
			idx = DELETE_IDX
			isError = true
		default:
			panic(fmt.Sprintf("Unknown operation: %s\n", key))
		}

		if !isError {
			results.Timestamps[idx] = append(results.Timestamps[idx], timestamp)
			results.Latencies[idx] = append(results.Latencies[idx], latency)
		} else {
			results.NumErrors[idx]++
		}

	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("error reading file %s: %w", filePath, err)
	}

	return results, nil
}

func parseTimeFile(filePath string) (string, error) {
	data, err := ioutil.ReadFile(filePath)
	if err != nil {
		return "", err
	}

	content := strings.ReplaceAll(string(data), "\n", "")
	return content, nil
}

// Example file: ./scripts/run_benchmark.py --num_clients=30 --num_threads=400 --db_type=http --workload_file=./workloads/read --ops=13333333 --workload_action=run --measurement_type=csv-file --keymax=10000000000 --batch_size=1
func parseCmdFile(filePath string) (map[string]string, error) {
	data, err := ioutil.ReadFile(filePath)
	if err != nil {
		return nil, err
	}

	content := strings.ReplaceAll(string(data), "\n", "")

	// TODO: this is dumb
	benchConfig := map[string]string{}
	keys := []string{"num_clients", "num_threads", "duration", "keymax", "target", "batch_size"}
	for _, key := range keys {
		regex := regexp.MustCompile(fmt.Sprintf("%s=(\\d+)", key))
		matches := regex.FindStringSubmatch(content)
		if len(matches) != 2 {
			return nil, fmt.Errorf("failed to match %s in cmd.txt", key)
		}

		benchConfig[key] = matches[1]
	}

	return benchConfig, nil
}

func main() {
	// Define and parse the command-line flag
	dirFlag := flag.String("dir", "", "Path to the directory containing foo.txt")
	flag.Parse()

	// Ensure the directory path is provided
	if *dirFlag == "" {
		fmt.Println("Error: You must specify the directory path using the -dir flag.")
		os.Exit(1)
	}

	startTimePath := filepath.Join(*dirFlag, "time.txt")
	startTime, err := parseTimeFile(startTimePath)
	if err != nil {
		fmt.Printf("Failed to parse %s: %s\n", startTimePath, err)
		os.Exit(1)
	}

	// Construct the full path to foo.txt
	cmdFilePath := filepath.Join(*dirFlag, "cmd.txt")
	if _, err := os.Stat(cmdFilePath); os.IsNotExist(err) {
		fmt.Printf("File not found: %s\n", cmdFilePath)
		os.Exit(1)
	}

	// Parse the file
	benchConfig, err := parseCmdFile(cmdFilePath)
	if err != nil {
		fmt.Printf("Error parsing command file: %v\n", err)
		os.Exit(1)
	}

	pattern := fmt.Sprintf("%s/**/results.csv", *dirFlag)
	resultsFiles, err := filepath.Glob(pattern)
	if err != nil {
		fmt.Printf("Error searching for files: %v\n", err)
		return
	}

	// Check if any matches were found
	if len(resultsFiles) == 0 {
		fmt.Println("No matching files found.")
		return
	}

	resultPool := pool.NewWithResults[*Results]().WithMaxGoroutines(8).WithErrors()

	for _, filePath := range resultsFiles {
		filePath := filePath
		resultPool.Go(func() (*Results, error) {
			return parseResultsFile(filePath)
		})
	}

	results, err := resultPool.Wait()
	if err != nil {
		fmt.Printf("Error during file processing: %v\n", err)
		return
	}

	benchType := filepath.Base(*dirFlag)
	numClients := mustInt(benchConfig["num_clients"])
	numThreads := mustInt(benchConfig["num_threads"])
	targetRps := mustInt(benchConfig["target"])
	benchName := fmt.Sprintf("numclients%02d_numthreads%03d_read%s_target%d", numClients, numThreads, benchType, targetRps)

	// Aggregate
	var allResults Results
	for i := 0; i < MAX_OPS; i++ {
		for _, result := range results {
			allResults.Latencies[i] = append(allResults.Latencies[i], result.Latencies[i]...)
			allResults.Timestamps[i] = append(allResults.Timestamps[i], result.Timestamps[i]...)
			allResults.NumErrors[i] += result.NumErrors[i]
		}

		sort.Ints(allResults.Latencies[i])
		sort.Ints(allResults.Timestamps[i])
	}

	fmt.Printf("### Benchmark %v\n", benchConfig)
	fmt.Printf("### Starting at %s\n", startTime)
	fmt.Printf("### Num clients: %s\n", benchConfig["num_clients"])
	fmt.Printf("### Num threads: %s\n", benchConfig["num_threads"])
	fmt.Printf("### Target RPS: %s\n", benchConfig["target"])

	// Open the file in append mode, create it if it doesn't exist
	csvFile, err := os.OpenFile("results.csv", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Printf("Error opening file: %v\n", err)
		return
	}
	defer csvFile.Close()

	totalRps := 0
	csv := fmt.Sprintf("%s,%s,", benchName, startTime)
	for op := 0; op < MAX_OPS; op++ {
		latencies := allResults.Latencies[op]
		if len(latencies) == 0 {
			continue
		}

		median := percentile(latencies, 50)
		p90 := percentile(latencies, 90)
		p99 := percentile(latencies, 99)
		ave := average(latencies)

		timestamps := allResults.Timestamps[op]
		// Remove the first and last 5% of the results to account for different clients
		// starting and finishing at slightly different times
		timestamps = sortAndTrim(timestamps, 5)
		timeDiff := timestamps[len(timestamps)-1] - timestamps[0]
		timeDiffSecs := timeDiff / 1000000
		rps := len(timestamps) / timeDiffSecs
		rps = rps * mustInt(benchConfig["batch_size"])
		totalRps += rps

		errors := allResults.NumErrors[op]
		nonErrors := len(latencies)
		percErrors := 100.0 * float64(errors) / (float64(nonErrors + errors))

		fmt.Printf("%s %s: ave: %d p50: %d p90 %d p99: %d total_time: %d rps: %d num_errors: %d (%.2f%%)\n", benchName, opAsString(op), ave/1000, median/1000, p90/1000, p99/1000, timeDiffSecs, rps, allResults.NumErrors[op], percErrors)

		csv += fmt.Sprintf("%d,%d,%d,%d,%d,", rps, ave/1000, median/1000, p90/1000, p99/1000)
	}

	fmt.Printf("%s TOTAL: %d RPS\n", benchName, totalRps)
	fmt.Printf("%s\n", csv[0:len(csv)-1])
	if _, err := csvFile.WriteString(fmt.Sprintf("%s\n", csv[0:len(csv)-1])); err != nil {
		fmt.Printf("Failed to write to csv file: %v\n", err)
		os.Exit(1)
	}

}
